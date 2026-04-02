"""Поиск по словарным статьям и форматирование результатов."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from models import DictionaryEntry, DictionarySource, SearchMatch, SearchMode
from normalization import comma_values, count_occurrences, normalize_query, tokenize


class EntryRepository(Protocol):
    """Контракт источника словарных статей."""

    def list_entries(self) -> list[DictionaryEntry]:
        """Вернуть все доступные словарные статьи.

        Returns:
            Список словарных статей из выбранного источника.
        """
        ...


class SearchProvider(Protocol):
    """Контракт поискового провайдера."""

    def search(self, query: str, mode: SearchMode) -> list[SearchMatch]:
        """Найти совпадения по запросу.

        Args:
            query: Нормализуемый поисковый запрос пользователя.
            mode: Режим поиска, влияющий на алгоритм ранжирования.

        Returns:
            Список совпадений с вычисленным рейтингом релевантности.
        """
        ...


class CsvSearchProvider:
    """Поисковый провайдер поверх CSV-репозитория."""

    def __init__(self, repository: EntryRepository) -> None:
        """Сохранить источник словарных статей для поиска.

        Args:
            repository: Репозиторий, из которого читаются словарные статьи.
        """
        self._repository = repository

    def search(self, query: str, mode: SearchMode) -> list[SearchMatch]:
        """Выполнить поиск по CSV-источнику.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска с выбранной стратегией ранжирования.

        Returns:
            Список найденных совпадений с оценкой релевантности.
        """
        normalized_query = normalize_query(query)
        matches: list[SearchMatch] = []

        for entry in self._repository.list_entries():
            score = self._match_score(entry, normalized_query, mode)
            if score > 0:
                matches.append(SearchMatch(entry=entry, score=score))

        return matches

    def _match_score(self, entry: DictionaryEntry, query: str, mode: SearchMode) -> int:
        if not query:
            return 0
        if mode == SearchMode.LITE:
            return self._lite_score(entry, query)
        return self._complex_score(entry, query)

    def _lite_score(self, entry: DictionaryEntry, query: str) -> int:
        score = 0
        word_candidates = comma_values(entry.word)
        translation_tokens = set(tokenize(entry.translation))
        comment_tokens = set(tokenize(entry.comments))

        if query in word_candidates:
            score = max(score, 500)
        if query in translation_tokens:
            score = max(score, 350)
        if entry.source == DictionarySource.CORE and query in comment_tokens:
            score = max(score, 120)
        return score

    def _complex_score(self, entry: DictionaryEntry, query: str) -> int:
        weighted_fields = (
            (10, entry.word),
            (8, entry.translation),
            (4, " ".join(entry.examples)),
            (3, " ".join(entry.notes)),
            (2, entry.comments),
        )

        score = sum(weight * count_occurrences(query, value) for weight, value in weighted_fields)
        if score == 0:
            return 0

        if normalize_query(entry.title) == query:
            score += 100
        elif query in normalize_query(entry.word):
            score += 30
        return score


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

        sorted_matches = sorted(
            unique_matches.values(),
            key=lambda item: (
                -item.score,
                0 if item.entry.source == DictionarySource.CORE else 1,
                normalize_query(item.entry.title),
            ),
        )
        return [match.entry for match in sorted_matches]


def format_entry(entry: DictionaryEntry) -> str:
    """Подготовить словарную статью к отправке в Telegram.

    Args:
        entry: Словарная статья, которую нужно превратить в текстовое сообщение.

    Returns:
        Отформатированный многострочный текст статьи.
    """
    lines: list[str] = []

    if entry.banner:
        lines.append(entry.banner)
        lines.append("")

    lines.append(entry.title)

    if entry.examples:
        lines.append("")
        lines.extend(entry.examples)

    extra_lines = list(entry.notes)
    if entry.comments:
        extra_lines.append(entry.comments)

    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    return "\n".join(line.rstrip() for line in lines).strip()
