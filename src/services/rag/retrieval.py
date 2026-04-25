"""Семантический retrieval поверх pgvector."""

from __future__ import annotations

from collections.abc import Sequence

from models import SearchMatch, SearchMode, SemanticSearchCandidate
from normalization import meaningful_tokens, normalize_query, tokenize
from repositories.postgres import PostgresDictionaryRepository

from .embeddings.base import EmbeddingProvider

_SEMANTIC_ALLOWED_CHUNK_TYPES = frozenset({"title", "translation", "example"})
_SEMANTIC_EXTRA_STOPWORDS = frozenset({"человек", "человека", "людей"})
_MAX_DISTANCE_WITHOUT_OVERLAP = 0.2
_MAX_DISTANCE_DELTA_WITHOUT_OVERLAP = 0.015


class PgvectorSearchProvider:
    """Семантический провайдер поиска поверх pgvector."""

    fallback_to_lite_on_error = True

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
            matches.append(SearchMatch(entry=candidate.entry, score=score, origin="semantic"))
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
        has_non_example_overlap = any(
            candidate.chunk_type in {"title", "translation"}
            and self._overlap_count(query, candidate) > 0
            for candidate in candidates
        )

        filtered: list[SemanticSearchCandidate] = []
        for candidate in candidates:
            if candidate.chunk_type not in _SEMANTIC_ALLOWED_CHUNK_TYPES:
                continue
            overlap_count = self._overlap_count(query, candidate)
            if candidate.chunk_type == "example" and has_non_example_overlap and overlap_count > 0:
                continue
            if overlap_count == 0 and meaningful_tokens:
                if best_overlap_distance is not None:
                    continue
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
        return meaningful_tokens(query, stopwords=_SEMANTIC_EXTRA_STOPWORDS)

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
