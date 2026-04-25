"""Оркестрация поиска по нескольким провайдерам."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from models import DictionaryEntry, DictionarySource, SearchMatch, SearchMode
from normalization import normalize_query

from .lexical import SearchProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    """Search response with fallback diagnostics for the Telegram layer."""

    entries: list[DictionaryEntry]
    requested_mode: SearchMode
    effective_mode: SearchMode
    fallback_provider: str | None = None
    fallback_reason: str | None = None

    @property
    def fallback_used(self) -> bool:
        """Return whether the original search mode was replaced by fallback mode."""
        return self.fallback_reason is not None


class DictionarySearchService:
    """Оркестрация поиска по нескольким провайдерам.

    Сюда можно подключить будущие RAG- и LLM-провайдеры, не меняя Telegram-слой.
    """

    def __init__(self, providers: Sequence[SearchProvider]) -> None:
        """Сохранить набор поисковых провайдеров.

        Args:
            providers: Источники поиска, результаты которых затем объединяются.
        """
        self._providers = tuple(providers)

    def search(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        """Найти и отсортировать словарные статьи по всем провайдерам.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска с нужной стратегией ранжирования.

        Returns:
            Уникальные статьи, отсортированные по релевантности и приоритету источника.
        """
        return self.search_with_diagnostics(query, mode).entries

    def search_with_diagnostics(self, query: str, mode: SearchMode) -> SearchResult:
        """Run search and include fallback metadata for observability.

        Returns:
            Search entries plus the effective mode and fallback reason, if any.
        """
        entries, fallback_provider, fallback_reason = self._search_entries(query, mode)
        return SearchResult(
            entries=entries,
            requested_mode=mode,
            effective_mode=SearchMode.LITE if fallback_reason is not None else mode,
            fallback_provider=fallback_provider,
            fallback_reason=fallback_reason,
        )

    def _search_entries(
        self,
        query: str,
        mode: SearchMode,
    ) -> tuple[list[DictionaryEntry], str | None, str | None]:
        matches: list[SearchMatch] = []
        for provider in self._providers:
            try:
                matches.extend(provider.search(query, mode))
            except Exception as exc:
                if mode == SearchMode.COMPLEX and getattr(
                    provider,
                    "fallback_to_lite_on_error",
                    False,
                ):
                    logger.warning(
                        "Complex search provider failed, falling back to lite mode",
                        exc_info=True,
                    )
                    entries, _, _ = self._search_entries(query, SearchMode.LITE)
                    return entries, type(provider).__name__, str(exc)
                raise

        grouped_matches: dict[tuple[str, str], list[SearchMatch]] = {}
        for match in matches:
            key = (match.entry.source.value, match.entry.title)
            grouped_matches.setdefault(key, []).append(match)

        reranked_matches = [
            self._rerank_group(match_group, mode) for match_group in grouped_matches.values()
        ]
        filtered_matches = self._filter_semantic_noise(
            tuple(reranked_matches),
            query,
            mode,
        )

        sorted_matches = sorted(
            filtered_matches,
            key=lambda item: (
                -item.score,
                0 if item.entry.source == DictionarySource.CORE else 1,
                normalize_query(item.entry.title),
            ),
        )
        return [match.entry for match in sorted_matches], None, None

    @staticmethod
    def _filter_semantic_noise(
        matches: Sequence[SearchMatch],
        query: str,
        mode: SearchMode,
    ) -> Sequence[SearchMatch]:
        if mode != SearchMode.COMPLEX:
            return matches
        if not DictionarySearchService._supports_fuzzy_fallback(normalize_query(query)):
            return matches

        best_score = max((match.score for match in matches), default=0)
        if best_score < 260:
            return matches

        return [match for match in matches if match.score >= 180]

    @staticmethod
    def _rerank_group(matches: Sequence[SearchMatch], mode: SearchMode) -> SearchMatch:
        best_match = max(matches, key=lambda item: item.score)
        if mode != SearchMode.COMPLEX:
            return best_match

        lexical_scores = [match.score for match in matches if match.origin == "lexical"]
        semantic_scores = [match.score for match in matches if match.origin == "semantic"]
        lexical_score = max(lexical_scores, default=0)
        semantic_score = max(semantic_scores, default=0)

        if lexical_score and semantic_score:
            boost = min(semantic_score // 3, 28)
            score = lexical_score + boost
            if score < best_match.score:
                score = best_match.score
            return SearchMatch(entry=best_match.entry, score=score, origin=best_match.origin)

        if semantic_score and len(matches) > 1:
            support = min(sum(semantic_scores) // 6, 24)
            score = semantic_score + support
            if score < best_match.score:
                score = best_match.score
            return SearchMatch(entry=best_match.entry, score=score, origin=best_match.origin)

        return best_match

    @staticmethod
    def _supports_fuzzy_fallback(query: str) -> bool:
        tokens = query.split()
        return len(tokens) == 1 and len(tokens[0]) >= 4
