"""Лексический поиск по словарным статьям."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from models import DictionaryEntry, DictionarySource, SearchMatch, SearchMode
from normalization import comma_values, normalize_query, stem_tokens, tokenize

_QUERY_STOPWORDS = frozenset(
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
    }
)


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


class LexicalSearchProvider:
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
                matches.append(SearchMatch(entry=entry, score=score, origin="lexical"))

        return matches

    def _load_entries(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        if isinstance(self._repository, CandidateEntryRepository):
            entries = self._repository.search_entries(query, mode)
            normalized_query = normalize_query(query)
            if entries or not self._supports_repository_fallback(normalized_query, mode):
                return entries
            return self._repository.list_entries()
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
        if score == 0 and self._supports_fuzzy_fallback(query):
            score = max(score, self._fuzzy_score(word_candidates, query, 430, 24))
            score = max(score, self._fuzzy_score(translation_tokens, query, 300, 18))
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
        query_stems = self._meaningful_query_stems(query)

        normalized_title = normalize_query(entry.title)
        word_candidates = comma_values(entry.word)
        title_tokens = tokenize(entry.title)
        translation_tokens = tokenize(entry.translation)
        example_tokens = tokenize(" ".join(entry.examples))
        note_tokens = tokenize(" ".join(entry.notes))
        comment_tokens = tokenize(entry.comments)
        title_stems = stem_tokens(entry.title)
        translation_stems = stem_tokens(entry.translation)
        example_stems = stem_tokens(" ".join(entry.examples))
        note_stems = stem_tokens(" ".join(entry.notes))
        comment_stems = stem_tokens(entry.comments)

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
            if self._supports_fuzzy_fallback(query):
                score += self._fuzzy_score(word_candidates, query, 320, 18)

        if self._supports_fuzzy_fallback(query):
            score += self._fuzzy_score(translation_tokens, query, 270, 14)

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

        if query_stems:
            stem_weighted_tokens = (
                (translation_stems, 95, 32),
                (title_stems, 70, 24),
                (example_stems, 24, 8),
                (note_stems, 18, 5),
                (comment_stems, 12, 3),
            )
            for tokens, coverage_weight, token_weight in stem_weighted_tokens:
                if self._has_stem_coverage(tokens, query_stems):
                    score += coverage_weight
                score += token_weight * self._matching_stem_count(tokens, query_stems)

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

    @staticmethod
    def _supports_fuzzy_fallback(query: str) -> bool:
        query_tokens = tokenize(query)
        return len(query_tokens) == 1 and len(query_tokens[0]) >= 4

    @classmethod
    def _supports_repository_fallback(cls, query: str, mode: SearchMode) -> bool:
        if cls._supports_fuzzy_fallback(query):
            return True
        if mode != SearchMode.COMPLEX:
            return False
        return len(cls._meaningful_query_stems(query)) >= 2

    @classmethod
    def _fuzzy_score(
        cls,
        candidates: tuple[str, ...],
        query: str,
        base_score: int,
        max_bonus: int,
    ) -> int:
        if not cls._supports_fuzzy_fallback(query):
            return 0

        max_distance = 1 if len(query) <= 5 else 2
        best_score = 0
        for candidate in candidates:
            distance = cls._bounded_edit_distance(query, candidate, max_distance)
            if distance is None:
                continue
            candidate_score = base_score + max(max_bonus - distance * 10, 0)
            if candidate_score > best_score:
                best_score = candidate_score
        return best_score

    @staticmethod
    def _bounded_edit_distance(left: str, right: str, max_distance: int) -> int | None:
        if left == right:
            return 0
        if abs(len(left) - len(right)) > max_distance:
            return None

        previous_row = list(range(len(right) + 1))
        for left_index, left_char in enumerate(left, start=1):
            current_row = [left_index]
            row_min = current_row[0]
            for right_index, right_char in enumerate(right, start=1):
                substitution_cost = 0 if left_char == right_char else 1
                current_value = min(
                    previous_row[right_index] + 1,
                    current_row[right_index - 1] + 1,
                    previous_row[right_index - 1] + substitution_cost,
                )
                current_row.append(current_value)
                row_min = min(row_min, current_value)
            if row_min > max_distance:
                return None
            previous_row = current_row

        distance = previous_row[-1]
        if distance > max_distance:
            return None
        return distance

    @staticmethod
    def _meaningful_query_stems(query: str) -> tuple[str, ...]:
        return tuple(
            stem for stem in stem_tokens(query) if len(stem) > 2 and stem not in _QUERY_STOPWORDS
        )

    @staticmethod
    def _has_stem_coverage(tokens: tuple[str, ...], query_stems: tuple[str, ...]) -> bool:
        if not tokens or not query_stems:
            return False
        token_pool = set(tokens)
        return all(stem in token_pool for stem in query_stems)

    @staticmethod
    def _matching_stem_count(tokens: tuple[str, ...], query_stems: tuple[str, ...]) -> int:
        if not tokens or not query_stems:
            return 0
        query_pool = set(query_stems)
        return sum(1 for token in tokens if token in query_pool)
