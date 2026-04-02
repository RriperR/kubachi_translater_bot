"""Семантический retrieval и индексация chunk-эмбеддингов для pgvector."""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from time import perf_counter

from models import RagChunkRecord, SearchMatch, SearchMode
from normalization import tokenize
from repositories.postgres_dictionary_repository import PostgresDictionaryRepository

_EMBEDDING_DIMENSIONS = 256
_EMBEDDING_PROVIDER = "local"
_EMBEDDING_MODEL = "hash-embedding"
_EMBEDDING_VERSION = "v1"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingVector:
    """Результат расчета эмбеддинга."""

    values: tuple[float, ...]

    @property
    def dimensions(self) -> int:
        """Вернуть размерность эмбеддинга.

        Returns:
            Число координат в векторе.
        """
        return len(self.values)

    def to_pgvector(self) -> str:
        """Преобразовать вектор в строковый литерал pgvector.

        Returns:
            Строка формата `[0.1,0.2,...]`, пригодная для SQL-вставки.
        """
        serialized = ",".join(f"{value:.8f}" for value in self.values)
        return f"[{serialized}]"


class HashEmbeddingProvider:
    """Локальный детерминированный embedder без внешнего API."""

    provider_name = _EMBEDDING_PROVIDER
    model_name = _EMBEDDING_MODEL
    version = _EMBEDDING_VERSION

    def __init__(self, dimensions: int = _EMBEDDING_DIMENSIONS) -> None:
        """Сохранить размерность эмбеддингов.

        Args:
            dimensions: Размерность результирующего вектора.
        """
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        """Вернуть размерность embeddings этого провайдера.

        Returns:
            Число координат в выходном embedding-векторе.
        """
        return self._dimensions

    def embed(self, text: str) -> EmbeddingVector:
        """Построить эмбеддинг строки.

        Args:
            text: Текст чанка или запроса.

        Returns:
            Нормализованный вектор фиксированной размерности.
        """
        buckets = [0.0] * self._dimensions
        for token in self._iter_features(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:4], byteorder="big") % self._dimensions
            sign = -1.0 if digest[4] % 2 else 1.0
            weight = 0.35 if token.startswith("tri:") else 1.0
            buckets[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0:
            return EmbeddingVector(tuple(0.0 for _ in range(self._dimensions)))

        return EmbeddingVector(tuple(value / norm for value in buckets))

    @staticmethod
    def _iter_features(text: str) -> Iterable[str]:
        tokens = tokenize(text)
        for token in tokens:
            yield f"tok:{token}"
            for trigram in HashEmbeddingProvider._char_ngrams(token, size=3):
                yield f"tri:{trigram}"

        for left, right in zip(tokens, tokens[1:], strict=False):
            yield f"bi:{left}_{right}"

    @staticmethod
    def _char_ngrams(token: str, size: int) -> Iterable[str]:
        if len(token) <= size:
            yield token
            return
        for index in range(len(token) - size + 1):
            yield token[index : index + size]


class DictionaryRagIndexer:
    """Индексатор чанков словаря в pgvector."""

    def __init__(
        self,
        repositories: Sequence[PostgresDictionaryRepository],
        embedding_provider: HashEmbeddingProvider,
        batch_size: int = 1024,
    ) -> None:
        """Сохранить репозитории и стратегию индексации.

        Args:
            repositories: Репозитории словарных источников.
            embedding_provider: Провайдер локальных эмбеддингов.
            batch_size: Размер пакета чанков за один SQL-проход.
        """
        self._repositories = tuple(repositories)
        self._embedding_provider = embedding_provider
        self._batch_size = batch_size

    def sync_pending(self) -> int:
        """Индексировать все чанки, помеченные как pending или error.

        Returns:
            Общее число успешно проиндексированных чанков.
        """
        total = 0
        for repository in self._repositories:
            total += self._sync_repository(repository)
        return total

    def _sync_repository(self, repository: PostgresDictionaryRepository) -> int:
        total_pending = repository.count_pending_rag_chunks()
        if total_pending == 0:
            logger.info("RAG index is up to date for source=%s", repository.source.value)
            return 0

        logger.info(
            "Start RAG indexing for source=%s: pending=%s, batch_size=%s",
            repository.source.value,
            total_pending,
            self._batch_size,
        )
        indexed = 0
        started_at = perf_counter()
        while True:
            pending_chunks = repository.fetch_pending_rag_chunks(self._batch_size)
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


class PgvectorSearchProvider:
    """Семантический провайдер поиска поверх pgvector."""

    def __init__(
        self,
        repository: PostgresDictionaryRepository,
        embedding_provider: HashEmbeddingProvider,
        top_k: int,
        max_distance: float,
    ) -> None:
        """Сохранить зависимости для semantic retrieval.

        Args:
            repository: Репозиторий статей выбранного источника.
            embedding_provider: Провайдер эмбеддингов запросов.
            top_k: Максимальное количество семантических кандидатов.
            max_distance: Порог cosine-distance для отсечения шума.
        """
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._top_k = top_k
        self._max_distance = max_distance

    def search(self, query: str, mode: SearchMode) -> list[SearchMatch]:
        """Найти семантически близкие статьи по запросу.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска.

        Returns:
            Список семантических совпадений с оценкой релевантности.
        """
        if mode != SearchMode.COMPLEX or not query.strip():
            return []

        query_embedding = self._embedding_provider.embed(query).to_pgvector()
        candidates = self._repository.semantic_search(query_embedding, self._top_k)

        matches: list[SearchMatch] = []
        for candidate in candidates:
            if candidate.distance > self._max_distance:
                continue
            score = self._semantic_score(candidate.distance, candidate.chunk_type)
            if score <= 0:
                continue
            matches.append(SearchMatch(entry=candidate.entry, score=score))
        return matches

    @staticmethod
    def _semantic_score(distance: float, chunk_type: str) -> int:
        chunk_bonus = {
            "title": 35,
            "translation": 28,
            "example": 16,
            "note": 12,
            "comment": 8,
        }.get(chunk_type, 0)
        similarity = max(0.0, 1.0 - distance)
        return int(similarity * 70) + chunk_bonus
