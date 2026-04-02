"""Поиск по словарным статьям и форматирование результатов."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from models import DictionaryEntry, DictionarySource, SearchMatch, SearchMode
from normalization import comma_values, normalize_query, tokenize


class EntryRepository(Protocol):
    """Контракт источника словарных статей."""

    def list_entries(self) -> list[DictionaryEntry]:
        """Вернуть все доступные словарные статьи.

        Returns:
            Список словарных статей из выбранного источника.
        """
        ...


@runtime_checkable
class CandidateEntryRepository(Protocol):
    """Контракт репозитория, который умеет отбирать кандидатов до ранжирования."""

    def search_entries(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        """Вернуть только потенциально релевантные статьи.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска, влияющий на SQL-фильтрацию.

        Returns:
            Ограниченный список кандидатов для финального ранжирования в Python.
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
    """Поисковый провайдер поверх репозитория словарных статей."""

    def __init__(self, repository: EntryRepository) -> None:
        """Сохранить источник словарных статей для поиска.

        Args:
            repository: Репозиторий, из которого читаются словарные статьи.
        """
        self._repository = repository

    def search(self, query: str, mode: SearchMode) -> list[SearchMatch]:
        """Выполнить поиск по источнику словарных статей.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска с выбранной стратегией ранжирования.

        Returns:
            Список найденных совпадений с оценкой релевантности.
        """
        normalized_query = normalize_query(query)
        matches: list[SearchMatch] = []

        for entry in self._load_entries(query, mode):
            score = self._match_score(entry, normalized_query, mode)
            if score > 0:
                matches.append(SearchMatch(entry=entry, score=score))

        return matches

    def _load_entries(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        if isinstance(self._repository, CandidateEntryRepository):
            return self._repository.search_entries(query, mode)
        return self._repository.list_entries()

    def _match_score(self, entry: DictionaryEntry, query: str, mode: SearchMode) -> int:
        if not query:
            return 0
        if mode == SearchMode.LITE:
            return self._lite_score(entry, query)
        return self._complex_score(entry, query)

    def _lite_score(self, entry: DictionaryEntry, query: str) -> int:
        score = 0
        word_candidates = comma_values(entry.word)
        translation_tokens = tokenize(entry.translation)
        comment_tokens = tokenize(entry.comments)

        if query in word_candidates:
            score = max(score, 500 + self._position_bonus(word_candidates, query, 40))
        if query in translation_tokens:
            score = max(score, 350 + self._position_bonus(translation_tokens, query, 25))
        if entry.source == DictionarySource.CORE and query in comment_tokens:
            score = max(score, 120 + self._position_bonus(comment_tokens, query, 10))
        return score

    @staticmethod
    def _position_bonus(tokens: tuple[str, ...], query: str, max_bonus: int) -> int:
        try:
            position = tokens.index(query)
        except ValueError:
            return 0
        return max(max_bonus - position, 0)

    def _complex_score(self, entry: DictionaryEntry, query: str) -> int:
        query_tokens = tokenize(query)
        if not query_tokens:
            return 0

        normalized_title = normalize_query(entry.title)
        word_candidates = comma_values(entry.word)
        title_tokens = tokenize(entry.title)
        translation_tokens = tokenize(entry.translation)
        example_tokens = tokenize(" ".join(entry.examples))
        note_tokens = tokenize(" ".join(entry.notes))
        comment_tokens = tokenize(entry.comments)

        score = 0
        if normalized_title == query:
            score += 260
        elif normalized_title.startswith(query):
            score += 180

        if query in word_candidates:
            score += 220
        else:
            score += self._prefix_bonus(word_candidates, query, 160)
            if any(query in candidate for candidate in word_candidates):
                score += 50

        weighted_tokens = (
            (title_tokens, 120, 70, 18),
            (translation_tokens, 80, 45, 12),
            (example_tokens, 40, 20, 4),
            (note_tokens, 25, 12, 3),
            (comment_tokens, 20, 8, 2),
        )
        for tokens, sequence_weight, coverage_weight, token_weight in weighted_tokens:
            sequence_matches = self._token_sequence_matches(tokens, query_tokens)
            if sequence_matches > 0:
                score += sequence_weight * sequence_matches

            if self._has_token_coverage(tokens, query_tokens):
                score += coverage_weight

            score += token_weight * self._matching_token_count(tokens, query_tokens)

        return score

    @staticmethod
    def _prefix_bonus(values: tuple[str, ...], query: str, max_bonus: int) -> int:
        prefix_offsets = [len(value) - len(query) for value in values if value.startswith(query)]
        if not prefix_offsets:
            return 0
        return max(max_bonus - min(prefix_offsets), 0)

    @staticmethod
    def _token_sequence_matches(tokens: tuple[str, ...], query_tokens: tuple[str, ...]) -> int:
        if not tokens or not query_tokens or len(tokens) < len(query_tokens):
            return 0

        window_size = len(query_tokens)
        return sum(
            1
            for index in range(len(tokens) - window_size + 1)
            if tokens[index : index + window_size] == query_tokens
        )

    @staticmethod
    def _has_token_coverage(tokens: tuple[str, ...], query_tokens: tuple[str, ...]) -> bool:
        if not tokens or not query_tokens:
            return False
        token_pool = set(tokens)
        return all(token in token_pool for token in query_tokens)

    @staticmethod
    def _matching_token_count(tokens: tuple[str, ...], query_tokens: tuple[str, ...]) -> int:
        if not tokens or not query_tokens:
            return 0
        query_pool = set(query_tokens)
        return sum(1 for token in tokens if token in query_pool)


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
