"""RAG-операции для PostgreSQL-репозитория словаря."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg2.extras import RealDictCursor, execute_values

from models import DictionarySource, RagChunkRecord, SemanticSearchCandidate
from normalization import compact_lines

from .base import PostgresRepositoryBase


class DictionaryRagRepositoryMixin(PostgresRepositoryBase):
    """Поведение PostgreSQL-репозитория для RAG-слоя."""

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
