"""Оркестрация поиска по нескольким провайдерам."""

from __future__ import annotations

from collections.abc import Sequence

from models import DictionaryEntry, DictionarySource, SearchMatch, SearchMode
from normalization import normalize_query

from .lexical import SearchProvider


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
        matches: list[SearchMatch] = []
        for provider in self._providers:
            matches.extend(provider.search(query, mode))

        unique_matches: dict[tuple[str, str], SearchMatch] = {}
        for match in matches:
            key = (match.entry.source.value, match.entry.title)
            previous = unique_matches.get(key)
            if previous is None or match.score > previous.score:
                unique_matches[key] = match

        filtered_matches = self._filter_semantic_noise(
            tuple(unique_matches.values()),
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
        return [match.entry for match in sorted_matches]

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
    def _supports_fuzzy_fallback(query: str) -> bool:
        tokens = query.split()
        return len(tokens) == 1 and len(tokens[0]) >= 4
