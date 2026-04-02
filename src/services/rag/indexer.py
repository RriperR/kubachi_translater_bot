"""Индексатор чанков словаря в pgvector."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from time import perf_counter

from models import RagChunkRecord
from repositories.postgres import PostgresDictionaryRepository

from .embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class DictionaryRagIndexer:
    """Индексатор чанков словаря в pgvector."""

    def __init__(
        self,
        repositories: Sequence[PostgresDictionaryRepository],
        embedding_provider: EmbeddingProvider,
        batch_size: int = 1024,
    ) -> None:
        """Сохранить репозитории и стратегию индексации.

        Args:
            repositories: Репозитории словарных источников.
            embedding_provider: Провайдер embeddings для индексации чанков.
            batch_size: Размер SQL-пакета чанков за один проход.
        """
        self._repositories = tuple(repositories)
        self._embedding_provider = embedding_provider
        self._batch_size = batch_size

    def sync_pending(self) -> int:
        """Индексировать все чанки, нуждающиеся в обновлении embeddings.

        Returns:
            Общее число успешно проиндексированных чанков.
        """
        total = 0
        for repository in self._repositories:
            total += self._sync_repository(repository)
        return total

    def _sync_repository(self, repository: PostgresDictionaryRepository) -> int:
        total_pending = repository.count_pending_rag_chunks(
            provider=self._embedding_provider.provider_name,
            model=self._embedding_provider.model_name,
            version=self._embedding_provider.version,
            dimensions=self._embedding_provider.dimensions,
        )
        if total_pending == 0:
            logger.info("RAG index is up to date for source=%s", repository.source.value)
            return 0

        logger.info(
            "Start RAG indexing for source=%s: pending=%s, batch_size=%s, model=%s",
            repository.source.value,
            total_pending,
            self._batch_size,
            self._embedding_provider.model_name,
        )
        indexed = 0
        started_at = perf_counter()
        while True:
            pending_chunks = repository.fetch_pending_rag_chunks(
                limit=self._batch_size,
                provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name,
                version=self._embedding_provider.version,
                dimensions=self._embedding_provider.dimensions,
            )
            if not pending_chunks:
                elapsed_seconds = perf_counter() - started_at
                logger.info(
                    "Finished RAG indexing for source=%s: indexed=%s, elapsed=%.2fs",
                    repository.source.value,
                    indexed,
                    elapsed_seconds,
                )
                return indexed

            indexed += self._index_batch(repository, pending_chunks)
            elapsed_seconds = max(perf_counter() - started_at, 0.001)
            remaining = max(total_pending - indexed, 0)
            rate = indexed / elapsed_seconds
            logger.info(
                (
                    "RAG indexing progress for source=%s: %s/%s processed, "
                    "remaining=%s, rate=%.1f chunks/s"
                ),
                repository.source.value,
                indexed,
                total_pending,
                remaining,
                rate,
            )

    def _index_batch(
        self,
        repository: PostgresDictionaryRepository,
        chunks: Sequence[RagChunkRecord],
    ) -> int:
        ready_items: list[tuple[int, str]] = []
        error_items: list[tuple[int, str]] = []
        try:
            embeddings = self._embedding_provider.embed_many(
                [chunk.normalized_chunk_text for chunk in chunks]
            )
            ready_items = [
                (chunk.chunk_id, embedding.to_pgvector())
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]
        except Exception:  # pragma: no cover
            for chunk in chunks:
                try:
                    embedding = self._embedding_provider.embed(chunk.normalized_chunk_text)
                except Exception as exc:  # pragma: no cover
                    error_items.append((chunk.chunk_id, str(exc)))
                    continue
                ready_items.append((chunk.chunk_id, embedding.to_pgvector()))

        indexed = repository.store_chunk_embeddings(
            items=ready_items,
            provider=self._embedding_provider.provider_name,
            model=self._embedding_provider.model_name,
            version=self._embedding_provider.version,
            dimensions=self._embedding_provider.dimensions,
        )
        repository.mark_chunk_embedding_errors(error_items)
        return indexed
