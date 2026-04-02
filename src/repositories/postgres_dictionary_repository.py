"""Работа со словарными статьями в PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from config import DatabaseConfig
from models import (
    DictionaryEntry,
    DictionarySource,
    RagChunkRecord,
    SearchMode,
    SemanticSearchCandidate,
    TelegramUser,
    UserSubmittedEntry,
)
from normalization import compact_lines, normalize_query, split_values, tokenize

_CANDIDATE_LIMIT = 250
_USER_ENTRY_BANNER = "!!!ПОЛЬЗОВАТЕЛЬСКИЙ ПЕРЕВОД!!!"


class PostgresDictionaryRepository:
    """Репозиторий словарных статей в PostgreSQL."""

    def __init__(self, config: DatabaseConfig, source: DictionarySource) -> None:
        """Сохранить настройки БД и источник словарных статей.

        Args:
            config: Настройки подключения к PostgreSQL.
            source: Источник статей, закрепленный за репозиторием.
        """
        self._config = config
        self._source = source

    @property
    def source(self) -> DictionarySource:
        """Вернуть словарный источник, закрепленный за репозиторием.

        Returns:
            Источник статей, с которым работает этот экземпляр репозитория.
        """
        return self._source

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        connection: Any = psycopg2.connect(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            password=self._config.password.get_secret_value(),
            dbname=self._config.database,
        )
        try:
            yield connection
        finally:
            connection.close()

    def has_entries(self) -> bool:
        """Проверить, импортированы ли статьи этого источника.

        Returns:
            `True`, если в таблице уже есть хотя бы одна статья данного источника.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT 1 FROM dictionary_entries WHERE source = %s LIMIT 1",
                (self._source.value,),
            )
            return cursor.fetchone() is not None

    def search_entries(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        """Вернуть кандидатов для поиска, отфильтрованных на стороне PostgreSQL.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска, влияющий на SQL-предикаты.

        Returns:
            Список словарных статей-кандидатов для дальнейшего ранжирования в Python.
        """
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []

        query_name, parameters = self._build_search_filter(normalized_query, mode)
        rows = self._fetch_entry_rows(query_name, parameters, limit=_CANDIDATE_LIMIT)
        return [self._row_to_entry(row) for row in rows]

    def sync_rag_chunks(self) -> int:
        """Синхронизировать RAG-чанки со словарными статьями текущего источника.

        Returns:
            Количество сохраненных чанков после полной синхронизации источника.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT id FROM dictionary_entries WHERE source = %s ORDER BY id",
                (self._source.value,),
            )
            entry_ids = [int(row["id"]) for row in cursor.fetchall()]

            total_chunks = 0
            for entry_id in entry_ids:
                total_chunks += self._sync_rag_chunks_for_entry(cursor, entry_id)

            connection.commit()

        return total_chunks

    def fetch_pending_rag_chunks(
        self,
        limit: int,
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> list[RagChunkRecord]:
        """Вернуть чанки, для которых нужно посчитать или обновить эмбеддинги.

        Args:
            limit: Максимальное количество чанков за один проход.
            provider: Имя активного embedding provider.
            model: Имя активной embedding-модели.
            version: Версия логики embeddings.
            dimensions: Ожидаемая размерность embeddings.

        Returns:
            Список чанков выбранного источника, ожидающих индексации.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    chunks.id AS chunk_id,
                    chunks.entry_id,
                    chunks.source,
                    chunks.chunk_type,
                    chunks.chunk_text,
                    chunks.normalized_chunk_text,
                    embeddings.content_hash
                FROM dictionary_entry_chunks AS chunks
                JOIN dictionary_chunk_embeddings AS embeddings
                    ON embeddings.chunk_id = chunks.id
                WHERE chunks.source = %s
                  AND (
                    embeddings.embedding_status <> 'ready'
                    OR embeddings.embedding IS NULL
                    OR embeddings.embedding_provider IS DISTINCT FROM %s
                    OR embeddings.embedding_model IS DISTINCT FROM %s
                    OR embeddings.embedding_version IS DISTINCT FROM %s
                    OR embeddings.vector_dimensions IS DISTINCT FROM %s
                  )
                ORDER BY chunks.id
                LIMIT %s
                """,
                (self._source.value, provider, model, version, dimensions, limit),
            )
            rows = cursor.fetchall()

        return [
            RagChunkRecord(
                chunk_id=int(row["chunk_id"]),
                entry_id=int(row["entry_id"]),
                source=DictionarySource(str(row["source"]).strip()),
                chunk_type=str(row["chunk_type"]).strip(),
                chunk_text=str(row["chunk_text"]),
                normalized_chunk_text=str(row["normalized_chunk_text"]),
                content_hash=str(row["content_hash"] or ""),
            )
            for row in rows
        ]

    def count_pending_rag_chunks(
        self,
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> int:
        """Подсчитать число чанков, которые еще не имеют актуального embedding.

        Args:
            provider: Имя активного embedding provider.
            model: Имя активной embedding-модели.
            version: Версия логики embeddings.
            dimensions: Ожидаемая размерность embeddings.

        Returns:
            Количество pending/error-чанков текущего словарного источника.
        """
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM dictionary_entry_chunks AS chunks
                JOIN dictionary_chunk_embeddings AS embeddings
                    ON embeddings.chunk_id = chunks.id
                WHERE chunks.source = %s
                  AND (
                    embeddings.embedding_status <> 'ready'
                    OR embeddings.embedding IS NULL
                    OR embeddings.embedding_provider IS DISTINCT FROM %s
                    OR embeddings.embedding_model IS DISTINCT FROM %s
                    OR embeddings.embedding_version IS DISTINCT FROM %s
                    OR embeddings.vector_dimensions IS DISTINCT FROM %s
                  )
                """,
                (self._source.value, provider, model, version, dimensions),
            )
            row = cursor.fetchone()
            if row is None:
                return 0
            return int(row[0])

    def store_chunk_embeddings(
        self,
        items: Sequence[tuple[int, str]],
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> int:
        """Сохранить пакет рассчитанных embeddings за одну транзакцию.

        Args:
            items: Пары `(chunk_id, embedding_literal)` для обновления.
            provider: Имя провайдера embeddings.
            model: Имя embedding-модели.
            version: Версия логики embeddings.
            dimensions: Размерность вектора.

        Returns:
            Число чанков, обновленных в текущем пакете.
        """
        if not items:
            return 0

        payload = [
            (chunk_id, embedding, provider, model, version, dimensions)
            for chunk_id, embedding in items
        ]
        with self._connect() as connection, connection.cursor() as cursor:
            execute_values(
                cursor,
                """
                UPDATE dictionary_chunk_embeddings AS target
                SET embedding = source.embedding::vector,
                    embedding_provider = source.provider,
                    embedding_model = source.model,
                    embedding_version = source.version,
                    vector_dimensions = source.dimensions,
                    embedding_status = 'ready',
                    last_indexed_at = NOW(),
                    last_error = ''
                FROM (
                    VALUES %s
                ) AS source(
                    chunk_id,
                    embedding,
                    provider,
                    model,
                    version,
                    dimensions
                )
                WHERE target.chunk_id = source.chunk_id
                """,
                payload,
            )
            connection.commit()
        return len(payload)

    def store_chunk_embedding(
        self,
        chunk_id: int,
        embedding: str,
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> None:
        """Сохранить рассчитанный эмбеддинг чанка.

        Args:
            chunk_id: Идентификатор чанка.
            embedding: Вектор в формате литерала pgvector.
            provider: Имя провайдера эмбеддингов.
            model: Имя модели эмбеддингов.
            version: Версия логики эмбеддингов.
            dimensions: Размерность вектора.
        """
        self.store_chunk_embeddings(
            items=((chunk_id, embedding),),
            provider=provider,
            model=model,
            version=version,
            dimensions=dimensions,
        )

    def mark_chunk_embedding_errors(self, items: Sequence[tuple[int, str]]) -> int:
        """Сохранить пакет ошибок индексации за одну транзакцию.

        Args:
            items: Пары `(chunk_id, error_text)` для обновления статуса.

        Returns:
            Число чанков, переведенных в состояние `error`.
        """
        if not items:
            return 0

        payload = [(chunk_id, error_text[:1000]) for chunk_id, error_text in items]
        with self._connect() as connection, connection.cursor() as cursor:
            execute_values(
                cursor,
                """
                UPDATE dictionary_chunk_embeddings AS target
                SET embedding_status = 'error',
                    last_error = source.error_text
                FROM (
                    VALUES %s
                ) AS source(chunk_id, error_text)
                WHERE target.chunk_id = source.chunk_id
                """,
                payload,
            )
            connection.commit()
        return len(payload)

    def mark_chunk_embedding_error(self, chunk_id: int, error_text: str) -> None:
        """Сохранить ошибку индексации чанка.

        Args:
            chunk_id: Идентификатор чанка.
            error_text: Текст ошибки, возникшей при индексации.
        """
        self.mark_chunk_embedding_errors(((chunk_id, error_text),))

    def semantic_search(
        self,
        embedding: str,
        top_k: int,
        provider: str,
        model: str,
        version: str,
        dimensions: int,
    ) -> list[SemanticSearchCandidate]:
        """Выполнить семантический поиск по pgvector-индексу.

        Args:
            embedding: Вектор запроса в формате литерала pgvector.
            top_k: Максимальное число возвращаемых кандидатов.
            provider: Имя активного embedding provider.
            model: Имя активной embedding-модели.
            version: Версия логики embeddings.
            dimensions: Ожидаемая размерность embeddings.

        Returns:
            Список семантических кандидатов с расстоянием до запроса.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    chunks.chunk_id,
                    chunks.entry_id,
                    chunks.chunk_type,
                    chunks.chunk_text,
                    chunks.distance
                FROM (
                    SELECT
                        entry_chunks.id AS chunk_id,
                        entry_chunks.entry_id,
                        entry_chunks.chunk_type,
                        entry_chunks.chunk_text,
                        embeddings.embedding <=> %s::vector AS distance
                    FROM dictionary_chunk_embeddings AS embeddings
                    JOIN dictionary_entry_chunks AS entry_chunks
                        ON entry_chunks.id = embeddings.chunk_id
                    WHERE entry_chunks.source = %s
                      AND embeddings.embedding_status = 'ready'
                      AND embeddings.embedding IS NOT NULL
                      AND embeddings.embedding_provider IS NOT DISTINCT FROM %s
                      AND embeddings.embedding_model IS NOT DISTINCT FROM %s
                      AND embeddings.embedding_version IS NOT DISTINCT FROM %s
                      AND embeddings.vector_dimensions IS NOT DISTINCT FROM %s
                    ORDER BY embeddings.embedding <=> %s::vector
                    LIMIT %s
                ) AS chunks
                ORDER BY chunks.distance ASC, chunks.chunk_id ASC
                """,
                (
                    embedding,
                    self._source.value,
                    provider,
                    model,
                    version,
                    dimensions,
                    embedding,
                    top_k,
                ),
            )
            rows = cursor.fetchall()

            candidates: list[SemanticSearchCandidate] = []
            for row in rows:
                entry_row = self._fetch_entry_row(int(row["entry_id"]), cursor)
                if entry_row is None:
                    continue
                candidates.append(
                    SemanticSearchCandidate(
                        entry=self._row_to_entry(entry_row),
                        chunk_id=int(row["chunk_id"]),
                        chunk_type=str(row["chunk_type"]).strip(),
                        chunk_text=str(row["chunk_text"]),
                        distance=float(row["distance"]),
                    )
                )

        return candidates

    def import_entries(self, entries: Iterable[DictionaryEntry]) -> int:
        """Импортировать словарные статьи в PostgreSQL.

        Args:
            entries: Последовательность нормализованных статей для загрузки.

        Returns:
            Число реально добавленных статей.
        """
        payload = list(entries)
        if not payload:
            return 0

        inserted = 0
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                for entry in payload:
                    entry_id = self._insert_entry(cursor, entry)
                    if entry_id is None:
                        continue
                    inserted += 1
                    self._replace_examples(cursor, entry_id, entry.examples)
                    self._replace_notes(cursor, entry_id, entry.notes)
                    self._replace_comments(cursor, entry_id, entry.comments)
            connection.commit()

        self.sync_rag_chunks()
        return inserted

    def list_entries(self) -> list[DictionaryEntry]:
        """Прочитать все статьи текущего источника из PostgreSQL.

        Returns:
            Список словарных статей этого источника.
        """
        rows = self._fetch_entry_rows("by_source", (self._source.value,))
        return [self._row_to_entry(row) for row in rows]

    def append_user_entry(self, entry: UserSubmittedEntry) -> None:
        """Добавить пользовательскую статью в PostgreSQL.

        Args:
            entry: Пользовательская статья, которую нужно сохранить.

        Raises:
            ValueError: Если метод вызван не для пользовательского репозитория.
        """
        if self._source != DictionarySource.USER:
            raise ValueError(
                "Добавление пользовательских статей доступно только для USER-репозитория"
            )

        examples = compact_lines(split_values(entry.phrases_raw, "%"))
        notes = compact_lines(split_values(entry.supporting_raw, "\\"))
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            inserted_id = self._insert_entry(
                cursor,
                DictionaryEntry(
                    source=self._source,
                    word=entry.word,
                    translation=entry.translation,
                    examples=examples,
                    notes=notes,
                    contributor_username=entry.contributor.username,
                    contributor_first_name=entry.contributor.first_name,
                    contributor_last_name=entry.contributor.last_name,
                ),
                chat_id=entry.contributor.chat_id,
            )
            if inserted_id is None:
                connection.commit()
                return

            self._replace_examples(cursor, inserted_id, examples)
            self._replace_notes(cursor, inserted_id, notes)
            self._sync_rag_chunks_for_entry(cursor, inserted_id)
            connection.commit()

    def append_comment(self, title: str, comment: str, author: TelegramUser) -> bool:
        """Добавить комментарий к существующей статье.

        Args:
            title: Заголовок статьи в формате `слово - перевод`.
            comment: Текст комментария пользователя.
            author: Автор комментария.

        Returns:
            `True`, если статья найдена и обновлена, иначе `False`.
        """
        comment_line = f"Пользователь оставил комментарий: {comment}"
        if author.username:
            comment_line += f" (@{author.username})"
        elif author.first_name:
            comment_line += f" ({author.first_name})"

        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT id
                FROM dictionary_entries
                WHERE source = %s
                  AND CONCAT(word, ' - ', translation) = %s
                """,
                (self._source.value, title),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return False

            entry_id = int(row["id"])
            contributor_id = self._ensure_contributor(cursor, author)
            cursor.execute(
                """
                INSERT INTO dictionary_entry_comments (
                    entry_id,
                    contributor_id,
                    text,
                    normalized_text
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    entry_id,
                    contributor_id,
                    comment_line,
                    self._normalize_token_text(comment_line),
                ),
            )
            self._sync_rag_chunks_for_entry(cursor, entry_id)
            connection.commit()
        return True

    def _fetch_entry_rows(
        self,
        query_name: str,
        parameters: tuple[object, ...],
        limit: int | None = None,
        cursor: Any | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            WITH examples_agg AS (
                SELECT
                    entry_id,
                    array_agg(text ORDER BY position) AS examples,
                    string_agg(normalized_text, ' ' ORDER BY position) AS normalized_examples
                FROM dictionary_entry_examples
                GROUP BY entry_id
            ),
            notes_agg AS (
                SELECT
                    entry_id,
                    array_agg(text ORDER BY position) AS notes,
                    string_agg(normalized_text, ' ' ORDER BY position) AS normalized_notes
                FROM dictionary_entry_notes
                GROUP BY entry_id
            ),
            comments_agg AS (
                SELECT
                    entry_id,
                    string_agg(text, E'\\n' ORDER BY id) AS comments,
                    string_agg(normalized_text, ' ' ORDER BY id) AS normalized_comments
                FROM dictionary_entry_comments
                GROUP BY entry_id
            )
            SELECT
                e.id,
                e.source,
                e.word,
                e.translation,
                COALESCE(examples_agg.examples, ARRAY[]::text[]) AS examples,
                COALESCE(notes_agg.notes, ARRAY[]::text[]) AS notes,
                COALESCE(comments_agg.comments, '') AS comments,
                COALESCE(examples_agg.normalized_examples, '') AS normalized_examples,
                COALESCE(notes_agg.normalized_notes, '') AS normalized_notes,
                COALESCE(comments_agg.normalized_comments, '') AS normalized_comments,
                contributors.username AS contributor_username,
                contributors.first_name AS contributor_first_name,
                contributors.last_name AS contributor_last_name
            FROM dictionary_entries AS e
            LEFT JOIN examples_agg ON examples_agg.entry_id = e.id
            LEFT JOIN notes_agg ON notes_agg.entry_id = e.id
            LEFT JOIN comments_agg ON comments_agg.entry_id = e.id
            LEFT JOIN dictionary_contributors AS contributors
                ON contributors.id = e.contributor_id
        """
        query_filters = {
            "by_source": "WHERE e.source = %s",
            "by_id": "WHERE e.id = %s",
            "search_lite": r"""
                WHERE e.source = %s
                  AND (
                    regexp_split_to_array(
                        regexp_replace(e.normalized_word, '\s*,\s*', ',', 'g'),
                        ','
                    ) @> ARRAY[%s]::text[]
                    OR regexp_split_to_array(e.normalized_translation, '\s+') @> ARRAY[%s]::text[]
                    OR (
                        e.source = %s
                        AND regexp_split_to_array(
                            COALESCE(comments_agg.normalized_comments, ''),
                            '\s+'
                        ) @> ARRAY[%s]::text[]
                    )
                  )
            """,
            "search_complex": r"""
                WHERE e.source = %s
                  AND (
                    to_tsvector(
                        'simple',
                        concat_ws(
                            ' ',
                            e.normalized_word,
                            e.normalized_translation,
                            COALESCE(examples_agg.normalized_examples, ''),
                            COALESCE(notes_agg.normalized_notes, ''),
                            COALESCE(comments_agg.normalized_comments, '')
                        )
                    ) @@ plainto_tsquery('simple', %s)
                    OR e.normalized_word LIKE %s
                    OR e.normalized_translation LIKE %s
                  )
            """,
        }
        query += "\n" + query_filters[query_name] + "\nORDER BY e.id"
        params = parameters
        if limit is not None:
            query += "\nLIMIT %s"
            params = (*parameters, limit)

        if cursor is not None:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as local_cursor,
        ):
            local_cursor.execute(query, params)
            return [dict(row) for row in local_cursor.fetchall()]

    def _fetch_entry_row(self, entry_id: int, cursor: Any) -> dict[str, Any] | None:
        rows = self._fetch_entry_rows("by_id", (entry_id,), cursor=cursor)
        if not rows:
            return None
        return rows[0]

    def _build_search_filter(
        self,
        query: str,
        mode: SearchMode,
    ) -> tuple[str, tuple[object, ...]]:
        if mode == SearchMode.LITE:
            return (
                "search_lite",
                (
                    self._source.value,
                    query,
                    query,
                    DictionarySource.CORE.value,
                    query,
                ),
            )

        return (
            "search_complex",
            (
                self._source.value,
                query,
                f"{query}%",
                f"{query}%",
            ),
        )

    def _ensure_contributor(self, cursor: Any, contributor: TelegramUser) -> int:
        return self._find_or_create_contributor(
            cursor,
            chat_id=contributor.chat_id,
            username=contributor.username,
            first_name=contributor.first_name,
            last_name=contributor.last_name,
        )

    def _find_or_create_contributor(
        self,
        cursor: Any,
        chat_id: int | None,
        username: str | None,
        first_name: str,
        last_name: str,
    ) -> int:
        if chat_id is not None:
            cursor.execute(
                """
                SELECT id
                FROM dictionary_contributors
                WHERE chat_id = %s
                """,
                (chat_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                contributor_id = int(row["id"])
                cursor.execute(
                    """
                    UPDATE dictionary_contributors
                    SET username = %s,
                        first_name = %s,
                        last_name = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (username, first_name, last_name, contributor_id),
                )
                return contributor_id

        cursor.execute(
            """
            SELECT id
            FROM dictionary_contributors
            WHERE chat_id IS NULL
              AND username IS NOT DISTINCT FROM %s
              AND first_name = %s
              AND last_name = %s
            LIMIT 1
            """,
            (username, first_name, last_name),
        )
        row = cursor.fetchone()
        if row is not None:
            return int(row["id"])

        cursor.execute(
            """
            INSERT INTO dictionary_contributors (
                chat_id,
                username,
                first_name,
                last_name
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (chat_id, username, first_name, last_name),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            raise RuntimeError("Не удалось создать автора словарной статьи")
        return int(inserted["id"])

    def _insert_entry(
        self,
        cursor: Any,
        entry: DictionaryEntry,
        chat_id: int | None = None,
    ) -> int | None:
        contributor_id = self._resolve_entry_contributor_id(cursor, entry, chat_id)
        cursor.execute(
            """
            INSERT INTO dictionary_entries (
                source,
                word,
                translation,
                normalized_word,
                normalized_translation,
                contributor_id
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, word, translation) DO NOTHING
            RETURNING id
            """,
            (
                self._source.value,
                entry.word,
                entry.translation,
                normalize_query(entry.word),
                self._normalize_token_text(entry.translation),
                contributor_id,
            ),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            return None
        return int(inserted["id"])

    def _resolve_entry_contributor_id(
        self,
        cursor: Any,
        entry: DictionaryEntry,
        chat_id: int | None,
    ) -> int | None:
        username = self._strip_text(entry.contributor_username)
        first_name = self._strip_text(entry.contributor_first_name) or ""
        last_name = self._strip_text(entry.contributor_last_name) or ""
        if chat_id is None and username is None and first_name == "" and last_name == "":
            return None

        return self._find_or_create_contributor(
            cursor,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

    def _replace_examples(self, cursor: Any, entry_id: int, examples: tuple[str, ...]) -> None:
        cursor.execute("DELETE FROM dictionary_entry_examples WHERE entry_id = %s", (entry_id,))
        if not examples:
            return

        cursor.executemany(
            """
            INSERT INTO dictionary_entry_examples (
                entry_id,
                position,
                text,
                normalized_text
            )
            VALUES (%s, %s, %s, %s)
            """,
            [
                (entry_id, index, example, self._normalize_token_text(example))
                for index, example in enumerate(examples)
            ],
        )

    def _replace_notes(self, cursor: Any, entry_id: int, notes: tuple[str, ...]) -> None:
        cursor.execute("DELETE FROM dictionary_entry_notes WHERE entry_id = %s", (entry_id,))
        if not notes:
            return

        cursor.executemany(
            """
            INSERT INTO dictionary_entry_notes (
                entry_id,
                position,
                text,
                normalized_text
            )
            VALUES (%s, %s, %s, %s)
            """,
            [
                (entry_id, index, note, self._normalize_token_text(note))
                for index, note in enumerate(notes)
            ],
        )

    def _replace_comments(self, cursor: Any, entry_id: int, comments: str) -> None:
        cursor.execute("DELETE FROM dictionary_entry_comments WHERE entry_id = %s", (entry_id,))
        comment_lines = compact_lines(comments.splitlines())
        if not comment_lines:
            return

        cursor.executemany(
            """
            INSERT INTO dictionary_entry_comments (
                entry_id,
                contributor_id,
                text,
                normalized_text
            )
            VALUES (%s, NULL, %s, %s)
            """,
            [(entry_id, line, self._normalize_token_text(line)) for line in comment_lines],
        )

    def _sync_rag_chunks_for_entry(self, cursor: Any, entry_id: int) -> int:
        row = self._fetch_entry_row(entry_id, cursor)
        if row is None:
            return 0

        chunks = self._build_rag_chunks(row)
        if not chunks:
            cursor.execute("DELETE FROM dictionary_entry_chunks WHERE entry_id = %s", (entry_id,))
            return 0

        cursor.executemany(
            """
            INSERT INTO dictionary_entry_chunks (
                entry_id,
                source,
                chunk_type,
                source_row_id,
                chunk_order,
                chunk_text,
                normalized_chunk_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entry_id, chunk_type, chunk_order) DO UPDATE
            SET source = EXCLUDED.source,
                source_row_id = EXCLUDED.source_row_id,
                chunk_text = EXCLUDED.chunk_text,
                normalized_chunk_text = EXCLUDED.normalized_chunk_text
            """,
            chunks,
        )
        cursor.execute(
            """
            INSERT INTO dictionary_chunk_embeddings (
                chunk_id,
                embedding_status,
                content_hash
            )
            SELECT
                id,
                'pending',
                md5(normalized_chunk_text)
            FROM dictionary_entry_chunks
            WHERE entry_id = %s
            ON CONFLICT (chunk_id) DO UPDATE
            SET content_hash = EXCLUDED.content_hash,
                embedding_status = CASE
                    WHEN dictionary_chunk_embeddings.content_hash = EXCLUDED.content_hash
                        THEN dictionary_chunk_embeddings.embedding_status
                    ELSE 'pending'
                END,
                last_error = CASE
                    WHEN dictionary_chunk_embeddings.content_hash = EXCLUDED.content_hash
                        THEN dictionary_chunk_embeddings.last_error
                    ELSE ''
                END
            """,
            (entry_id,),
        )
        return len(chunks)

    def _build_rag_chunks(self, row: dict[str, Any]) -> list[tuple[object, ...]]:
        source = str(row["source"]).strip()
        entry_id = int(row["id"])
        examples = tuple(row.get("examples") or ())
        notes = tuple(row.get("notes") or ())
        comment_lines = compact_lines(str(row.get("comments") or "").splitlines())

        raw_chunks: list[tuple[str, int | None, int, str]] = [
            ("title", None, 0, f"{str(row['word']).strip()} - {str(row['translation']).strip()}"),
            ("translation", None, 0, str(row["translation"]).strip()),
        ]
        raw_chunks.extend(
            ("example", index, index, example.strip())
            for index, example in enumerate(examples)
            if example and example.strip()
        )
        raw_chunks.extend(
            ("note", index, index, note.strip())
            for index, note in enumerate(notes)
            if note and note.strip()
        )
        raw_chunks.extend(
            ("comment", index, index, comment.strip())
            for index, comment in enumerate(comment_lines)
            if comment and comment.strip()
        )

        return [
            (
                entry_id,
                source,
                chunk_type,
                source_row_id,
                chunk_order,
                chunk_text,
                self._normalize_token_text(chunk_text),
            )
            for chunk_type, source_row_id, chunk_order, chunk_text in raw_chunks
        ]

    @staticmethod
    def _normalize_token_text(text: str) -> str:
        return " ".join(tokenize(text))

    @staticmethod
    def _strip_text(value: object | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _row_to_entry(self, row: dict[str, Any]) -> DictionaryEntry:
        source = DictionarySource(str(row["source"]).strip())
        return DictionaryEntry(
            source=source,
            word=str(row["word"]).strip(),
            translation=str(row["translation"]).strip(),
            examples=tuple(row.get("examples") or ()),
            notes=tuple(row.get("notes") or ()),
            comments=str(row.get("comments") or "").strip(),
            contributor_username=self._strip_text(row.get("contributor_username")),
            contributor_first_name=self._strip_text(row.get("contributor_first_name")),
            contributor_last_name=self._strip_text(row.get("contributor_last_name")),
            banner=_USER_ENTRY_BANNER if source == DictionarySource.USER else None,
        )
