"""Работа со словарными статьями в PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DatabaseConfig
from models import DictionaryEntry, DictionarySource, SearchMode, TelegramUser, UserSubmittedEntry
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

    def sync_normalized_storage(self) -> int:
        """Перенести legacy-поля статьи в нормализованные дочерние таблицы.

        Returns:
            Количество обработанных статей выбранного источника.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    id,
                    source,
                    word,
                    translation,
                    examples,
                    notes,
                    comments,
                    contributor_id,
                    contributor_username,
                    contributor_first_name,
                    contributor_last_name
                FROM dictionary_entries
                WHERE source = %s
                ORDER BY id
                """,
                (self._source.value,),
            )
            rows = cursor.fetchall()

            for row in rows:
                entry_id = int(row["id"])
                contributor_id = self._sync_entry_contributor(cursor, row)
                self._sync_examples_from_legacy(cursor, entry_id, tuple(row.get("examples") or ()))
                self._sync_notes_from_legacy(cursor, entry_id, tuple(row.get("notes") or ()))
                self._sync_comments_from_legacy(cursor, entry_id, str(row.get("comments") or ""))
                self._refresh_entry_cache(cursor, entry_id, contributor_id)

            connection.commit()

        return len(rows)

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

    def import_entries(self, entries: Iterable[DictionaryEntry]) -> int:
        """Импортировать словарные статьи в PostgreSQL.

        Args:
            entries: Последовательность нормализованных статей для загрузки.

        Returns:
            Число реально добавленных статей.
        """
        payload = [self._entry_to_row(entry) for entry in entries]
        if not payload:
            return 0

        inserted = 0
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for row in payload:
                    cursor.execute(
                        """
                        INSERT INTO dictionary_entries (
                            source,
                            word,
                            translation,
                            examples,
                            notes,
                            comments,
                            normalized_word,
                            normalized_translation,
                            normalized_comments,
                            normalized_search_text,
                            contributor_username,
                            contributor_first_name,
                            contributor_last_name,
                            banner
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source, word, translation) DO NOTHING
                        """,
                        row,
                    )
                    inserted += cursor.rowcount
            connection.commit()

        self.sync_normalized_storage()
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
            contributor_id = self._ensure_contributor(cursor, entry.contributor)
            cursor.execute(
                """
                INSERT INTO dictionary_entries (
                    source,
                    word,
                    translation,
                    examples,
                    notes,
                    comments,
                    normalized_word,
                    normalized_translation,
                    normalized_comments,
                    normalized_search_text,
                    contributor_id,
                    contributor_username,
                    contributor_first_name,
                    contributor_last_name,
                    banner
                )
                VALUES (%s, %s, %s, %s, %s, '', %s, %s, '', %s, %s, %s, %s, %s, NULL)
                RETURNING id
                """,
                (
                    self._source.value,
                    entry.word,
                    entry.translation,
                    list(examples),
                    list(notes),
                    normalize_query(entry.word),
                    self._normalize_token_text(entry.translation),
                    self._build_search_text(
                        entry.word,
                        entry.translation,
                        examples,
                        notes,
                        "",
                    ),
                    contributor_id,
                    entry.contributor.username,
                    entry.contributor.first_name,
                    entry.contributor.last_name,
                ),
            )
            inserted_row = cursor.fetchone()
            if inserted_row is None:
                connection.commit()
                return

            entry_id = int(inserted_row["id"])
            self._replace_examples(cursor, entry_id, examples)
            self._replace_notes(cursor, entry_id, notes)
            self._refresh_entry_cache(cursor, entry_id, contributor_id)
            self._sync_rag_chunks_for_entry(cursor, entry_id)
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
            self._refresh_entry_cache(cursor, entry_id)
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

    def _sync_entry_contributor(self, cursor: Any, row: dict[str, Any]) -> int | None:
        if row.get("contributor_id") is not None:
            return int(row["contributor_id"])

        username = self._strip_text(row.get("contributor_username"))
        first_name = self._strip_text(row.get("contributor_first_name")) or ""
        last_name = self._strip_text(row.get("contributor_last_name")) or ""
        if username is None and first_name == "" and last_name == "":
            return None

        contributor_id = self._find_or_create_contributor(
            cursor,
            chat_id=None,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        cursor.execute(
            "UPDATE dictionary_entries SET contributor_id = %s WHERE id = %s",
            (contributor_id, int(row["id"])),
        )
        return contributor_id

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

    def _sync_examples_from_legacy(
        self,
        cursor: Any,
        entry_id: int,
        examples: tuple[str, ...],
    ) -> None:
        if self._has_child_rows(cursor, "dictionary_entry_examples", entry_id):
            return
        self._replace_examples(cursor, entry_id, compact_lines(examples))

    def _sync_notes_from_legacy(self, cursor: Any, entry_id: int, notes: tuple[str, ...]) -> None:
        if self._has_child_rows(cursor, "dictionary_entry_notes", entry_id):
            return
        self._replace_notes(cursor, entry_id, compact_lines(notes))

    def _sync_comments_from_legacy(self, cursor: Any, entry_id: int, comments: str) -> None:
        if self._has_child_rows(cursor, "dictionary_entry_comments", entry_id):
            return

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

    def _refresh_entry_cache(
        self,
        cursor: Any,
        entry_id: int,
        contributor_id: int | None = None,
    ) -> None:
        row = self._fetch_entry_row(entry_id, cursor)
        if row is None:
            return

        effective_contributor_id = contributor_id
        if effective_contributor_id is None:
            cursor.execute(
                "SELECT contributor_id FROM dictionary_entries WHERE id = %s",
                (entry_id,),
            )
            contributor_row = cursor.fetchone()
            if contributor_row is not None:
                effective_contributor_id = contributor_row["contributor_id"]

        cursor.execute(
            """
            UPDATE dictionary_entries
            SET examples = %s,
                notes = %s,
                comments = %s,
                normalized_comments = %s,
                normalized_search_text = %s,
                contributor_id = COALESCE(%s, contributor_id)
            WHERE id = %s
            """,
            (
                list(row.get("examples") or ()),
                list(row.get("notes") or ()),
                str(row.get("comments") or ""),
                self._normalize_token_text(str(row.get("comments") or "")),
                self._build_search_text(
                    str(row["word"]),
                    str(row["translation"]),
                    tuple(row.get("examples") or ()),
                    tuple(row.get("notes") or ()),
                    str(row.get("comments") or ""),
                ),
                effective_contributor_id,
                entry_id,
            ),
        )

    def _sync_rag_chunks_for_entry(self, cursor: Any, entry_id: int) -> int:
        row = self._fetch_entry_row(entry_id, cursor)
        if row is None:
            return 0

        chunks = self._build_rag_chunks(row)
        cursor.execute("DELETE FROM dictionary_entry_chunks WHERE entry_id = %s", (entry_id,))
        if not chunks:
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

    def _entry_to_row(self, entry: DictionaryEntry) -> tuple[object, ...]:
        return (
            self._source.value,
            entry.word,
            entry.translation,
            list(entry.examples),
            list(entry.notes),
            entry.comments,
            normalize_query(entry.word),
            self._normalize_token_text(entry.translation),
            self._normalize_token_text(entry.comments),
            self._build_search_text(
                entry.word,
                entry.translation,
                entry.examples,
                entry.notes,
                entry.comments,
            ),
            entry.contributor_username,
            entry.contributor_first_name,
            entry.contributor_last_name,
            None,
        )

    @staticmethod
    def _build_search_text(
        word: str,
        translation: str,
        examples: Iterable[str],
        notes: Iterable[str],
        comments: str,
    ) -> str:
        parts = [
            normalize_query(word),
            PostgresDictionaryRepository._normalize_token_text(translation),
            *(PostgresDictionaryRepository._normalize_token_text(example) for example in examples),
            *(PostgresDictionaryRepository._normalize_token_text(note) for note in notes),
            PostgresDictionaryRepository._normalize_token_text(comments),
        ]
        return " ".join(part for part in parts if part)

    @staticmethod
    def _normalize_token_text(text: str) -> str:
        return " ".join(tokenize(text))

    @staticmethod
    def _has_child_rows(cursor: Any, table_name: str, entry_id: int) -> bool:
        allowed_queries = {
            "dictionary_entry_examples": (
                "SELECT 1 FROM dictionary_entry_examples WHERE entry_id = %s LIMIT 1"
            ),
            "dictionary_entry_notes": (
                "SELECT 1 FROM dictionary_entry_notes WHERE entry_id = %s LIMIT 1"
            ),
            "dictionary_entry_comments": (
                "SELECT 1 FROM dictionary_entry_comments WHERE entry_id = %s LIMIT 1"
            ),
        }
        query = allowed_queries[table_name]
        cursor.execute(query, (entry_id,))
        return cursor.fetchone() is not None

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
