"""Семантический retrieval и индексация chunk-эмбеддингов для pgvector."""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from config import AppConfig
from models import RagChunkRecord, SearchMatch, SearchMode, SemanticSearchCandidate
from normalization import normalize_query, tokenize
from repositories.postgres_dictionary_repository import PostgresDictionaryRepository

_HASH_EMBEDDING_PROVIDER = "local"
_HASH_EMBEDDING_MODEL = "hash-embedding"
_HASH_EMBEDDING_VERSION = "v1"
_SENTENCE_TRANSFORMER_PROVIDER = "sentence-transformers"
_SENTENCE_TRANSFORMER_VERSION = "v1"
_SEMANTIC_ALLOWED_CHUNK_TYPES = frozenset({"title", "translation", "example"})
_SEMANTIC_QUERY_STOPWORDS = frozenset(
    {
        "и",
        "или",
        "как",
        "что",
        "кто",
        "где",
        "куда",
        "откуда",
        "зачем",
        "почему",
        "ли",
        "при",
        "по",
        "в",
        "во",
        "на",
        "с",
        "со",
        "к",
        "ко",
        "у",
        "о",
        "об",
        "про",
        "для",
        "из",
        "а",
        "но",
        "же",
        "это",
        "этот",
        "эта",
        "эти",
        "человек",
        "человека",
        "людей",
    }
)
_MAX_DISTANCE_WITHOUT_OVERLAP = 0.2
_MAX_DISTANCE_DELTA_WITHOUT_OVERLAP = 0.015

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


class EmbeddingProvider(Protocol):
    """Контракт провайдера text embeddings для индексации и поиска."""

    provider_name: str
    model_name: str
    version: str

    @property
    def dimensions(self) -> int:
        """Вернуть размерность embeddings провайдера.

        Returns:
            Число координат в выходном векторе.
        """
        ...

    def embed(self, text: str) -> EmbeddingVector:
        """Построить embedding одного текста.

        Args:
            text: Текст запроса или чанка.

        Returns:
            Построенный embedding-вектор.
        """
        ...

    def embed_many(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Построить embeddings для нескольких текстов сразу.

        Args:
            texts: Последовательность текстов для пакетной индексации.

        Returns:
            Векторы в том же порядке, что и входные тексты.
        """
        ...


class HashEmbeddingProvider:
    """Локальный детерминированный embedder без внешнего API."""

    provider_name = _HASH_EMBEDDING_PROVIDER
    model_name = _HASH_EMBEDDING_MODEL
    version = _HASH_EMBEDDING_VERSION

    def __init__(self, dimensions: int = 256) -> None:
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

    def embed_many(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Построить embeddings для набора текстов.

        Args:
            texts: Последовательность текстов для индексации.

        Returns:
            Список embedding-векторов в исходном порядке.
        """
        return [self.embed(text) for text in texts]

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


class SentenceTransformerEmbeddingProvider:
    """Embedding provider поверх sentence-transformers."""

    provider_name = _SENTENCE_TRANSFORMER_PROVIDER
    version = _SENTENCE_TRANSFORMER_VERSION

    def __init__(
        self,
        model_name: str,
        dimensions: int,
        batch_size: int,
        device: str,
    ) -> None:
        """Сохранить настройки локальной embedding-модели.

        Args:
            model_name: Идентификатор модели в Hugging Face Hub.
            dimensions: Ожидаемая размерность embeddings.
            batch_size: Размер inference-пакета для `encode`.
            device: Устройство для расчета embeddings, например `cpu`.
        """
        self.model_name = model_name
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._device = device
        self._model: Any | None = None

    @property
    def dimensions(self) -> int:
        """Вернуть размерность embeddings модели.

        Returns:
            Число координат в векторе этой модели.
        """
        return self._dimensions

    def embed(self, text: str) -> EmbeddingVector:
        """Построить embedding одного текста.

        Args:
            text: Текст запроса или чанка.

        Returns:
            Embedding-вектор заданной размерности.
        """
        embeddings = self.embed_many((text,))
        return embeddings[0]

    def embed_many(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Построить embeddings для набора текстов пакетно.

        Args:
            texts: Последовательность текстов для индексации или поиска.

        Returns:
            Embedding-векторы в исходном порядке.

        Raises:
            ValueError: Если модель вернула неожиданную размерность.
        """
        if not texts:
            return []

        model = self._get_model()
        raw_embeddings = model.encode(
            list(texts),
            batch_size=self._batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        vectors: list[EmbeddingVector] = []
        for raw_embedding in raw_embeddings:
            values = tuple(float(value) for value in raw_embedding.tolist())
            vector = EmbeddingVector(values)
            if vector.dimensions != self._dimensions:
                raise ValueError(
                    "Размерность embeddings модели не совпадает с конфигурацией: "
                    f"expected={self._dimensions}, actual={vector.dimensions}"
                )
            vectors.append(vector)
        return vectors

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Пакет sentence-transformers не установлен. "
                "Установите зависимости проекта перед запуском RAG."
            ) from exc

        self._model = SentenceTransformer(self.model_name, device=self._device)
        return self._model


def build_embedding_provider(config: AppConfig) -> EmbeddingProvider:
    """Собрать embedding provider из конфигурации приложения.

    Args:
        config: Корневая конфигурация приложения.

    Returns:
        Настроенный провайдер embeddings для поиска и индексации.

    Raises:
        ValueError: Если указан неподдерживаемый тип embedding provider.
    """
    provider_name = config.rag_embedding_provider.strip().lower()
    if provider_name == "hash":
        return HashEmbeddingProvider(dimensions=config.rag_embedding_dimensions)
    if provider_name == "sentence-transformers":
        return SentenceTransformerEmbeddingProvider(
            model_name=config.rag_embedding_model,
            dimensions=config.rag_embedding_dimensions,
            batch_size=config.rag_embedding_batch_size,
            device=config.rag_embedding_device,
        )
    raise ValueError(f"Неподдерживаемый RAG embedding provider: {config.rag_embedding_provider}")


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


class PgvectorSearchProvider:
    """Семантический провайдер поиска поверх pgvector."""

    def __init__(
        self,
        repository: PostgresDictionaryRepository,
        embedding_provider: EmbeddingProvider,
        top_k: int,
        max_distance: float,
    ) -> None:
        """Сохранить зависимости для semantic retrieval.

        Args:
            repository: Репозиторий статей выбранного источника.
            embedding_provider: Провайдер embeddings поисковых запросов.
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
        candidates = self._repository.semantic_search(
            embedding=query_embedding,
            top_k=self._top_k,
            provider=self._embedding_provider.provider_name,
            model=self._embedding_provider.model_name,
            version=self._embedding_provider.version,
            dimensions=self._embedding_provider.dimensions,
        )
        filtered_candidates = self._filter_candidates(query, candidates)

        matches: list[SearchMatch] = []
        for candidate in filtered_candidates:
            if candidate.distance > self._max_distance:
                continue
            overlap_count = self._overlap_count(query, candidate)
            score = self._semantic_score(candidate.distance, candidate.chunk_type, overlap_count)
            if score <= 0:
                continue
            matches.append(SearchMatch(entry=candidate.entry, score=score))
        return matches

    @staticmethod
    def _semantic_score(distance: float, chunk_type: str, overlap_count: int) -> int:
        chunk_bonus = {
            "title": 18,
            "translation": 24,
            "example": 14,
        }.get(chunk_type, 0)
        similarity = max(0.0, 1.0 - distance)
        overlap_bonus = min(overlap_count, 3) * 22
        no_overlap_penalty = 24 if overlap_count == 0 else 0
        return int(similarity * 85) + chunk_bonus + overlap_bonus - no_overlap_penalty

    def _filter_candidates(
        self,
        query: str,
        candidates: Sequence[SemanticSearchCandidate],
    ) -> list[SemanticSearchCandidate]:
        meaningful_tokens = self._meaningful_query_tokens(query)
        overlap_distances = [
            candidate.distance
            for candidate in candidates
            if candidate.chunk_type in _SEMANTIC_ALLOWED_CHUNK_TYPES
            and self._overlap_count(query, candidate) > 0
        ]
        best_overlap_distance = min(overlap_distances) if overlap_distances else None

        filtered: list[SemanticSearchCandidate] = []
        for candidate in candidates:
            if candidate.chunk_type not in _SEMANTIC_ALLOWED_CHUNK_TYPES:
                continue
            overlap_count = self._overlap_count(query, candidate)
            if overlap_count == 0 and meaningful_tokens:
                if candidate.chunk_type == "example":
                    continue
                if candidate.distance > _MAX_DISTANCE_WITHOUT_OVERLAP:
                    continue
                if (
                    best_overlap_distance is not None
                    and candidate.distance
                    > best_overlap_distance + _MAX_DISTANCE_DELTA_WITHOUT_OVERLAP
                ):
                    continue
            filtered.append(candidate)
        return filtered

    @staticmethod
    def _meaningful_query_tokens(query: str) -> tuple[str, ...]:
        return tuple(
            token
            for token in tokenize(query)
            if len(token) > 2 and token not in _SEMANTIC_QUERY_STOPWORDS
        )

    def _overlap_count(self, query: str, candidate: SemanticSearchCandidate) -> int:
        query_tokens = set(self._meaningful_query_tokens(query))
        if not query_tokens:
            return 0

        candidate_text = " ".join(
            (
                candidate.entry.word,
                candidate.entry.translation,
                candidate.chunk_text,
            )
        )
        candidate_tokens = set(tokenize(normalize_query(candidate_text)))
        return len(query_tokens & candidate_tokens)
