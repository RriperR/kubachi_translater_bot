"""Тесты поиска по словарю."""

from __future__ import annotations

from models import DictionaryEntry, DictionarySource, SearchMatch, SearchMode
from services.search import DictionarySearchService, LexicalSearchProvider


class InMemoryRepository:
    """Простой репозиторий статей для тестов."""

    def __init__(self, entries: list[DictionaryEntry]) -> None:
        self._entries = entries

    def list_entries(self) -> list[DictionaryEntry]:
        """Вернуть тестовые статьи.

        Returns:
            Список словарных статей, переданных в конструктор.
        """
        return self._entries


class CandidateRepository(InMemoryRepository):
    """Тестовый репозиторий с собственным этапом отбора кандидатов."""

    def search_entries(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        """Вернуть ограниченный набор кандидатов.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска, переданный провайдеру.

        Returns:
            Только те статьи, которые репозиторий считает кандидатами.
        """
        assert query == "дом"
        assert mode == SearchMode.LITE
        return [
            DictionaryEntry(
                source=DictionarySource.CORE,
                word="аIа",
                translation="дом",
            )
        ]


class FuzzyFallbackRepository(InMemoryRepository):
    """Репозиторий, который не находит SQL-кандидатов для опечатки."""

    def search_entries(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        """Вернуть пустой результат для проверки fallback на полный словарь.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска.

        Returns:
            Пустой список кандидатов.
        """
        assert query == "првет"
        assert mode == SearchMode.COMPLEX
        return []


class StaticSearchProvider:
    """Поисковый провайдер с заранее заданными результатами."""

    def __init__(self, matches: list[SearchMatch]) -> None:
        self._matches = matches

    def search(self, query: str, mode: SearchMode) -> list[SearchMatch]:
        """Вернуть заранее зафиксированные совпадения.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска.

        Returns:
            Список тестовых совпадений.
        """
        return self._matches


def test_lite_search_ignores_examples_and_notes() -> None:
    """Простой режим не должен искать по примерам и примечаниям."""
    provider = LexicalSearchProvider(
        InMemoryRepository(
            [
                DictionaryEntry(
                    source=DictionarySource.CORE,
                    word="аIа",
                    translation="дом",
                    examples=("тестовая фраза",),
                    notes=("редкое слово",),
                )
            ]
        )
    )

    assert provider.search("тестовая", SearchMode.LITE) == []
    assert provider.search("редкое", SearchMode.LITE) == []


def test_provider_uses_repository_candidates_when_available() -> None:
    """Провайдер должен брать кандидатов из репозитория, если тот поддерживает SQL-поиск."""
    provider = LexicalSearchProvider(
        CandidateRepository(
            [
                DictionaryEntry(
                    source=DictionarySource.CORE,
                    word="сад",
                    translation="огород",
                )
            ]
        )
    )

    results = provider.search("дом", SearchMode.LITE)

    assert [match.entry.title for match in results] == ["аIа - дом"]


def test_complex_search_falls_back_to_full_dictionary_for_single_typo() -> None:
    """Опечатка в одном токене должна вызывать fuzzy fallback вместо пустого SQL-результата."""
    provider = LexicalSearchProvider(
        FuzzyFallbackRepository(
            [
                DictionaryEntry(
                    source=DictionarySource.CORE,
                    word="салам",
                    translation="привет",
                )
            ]
        )
    )

    results = provider.search("првет", SearchMode.COMPLEX)

    assert [match.entry.title for match in results] == ["салам - привет"]


def test_lite_search_prefers_word_match_over_translation() -> None:
    """В простом режиме совпадение по слову должно быть выше совпадения по переводу."""
    service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(
                InMemoryRepository(
                    [
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="гьул",
                            translation="яблоко",
                        ),
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="сад",
                            translation="гьул",
                        ),
                    ]
                )
            ),
        )
    )

    results = service.search("гьул", SearchMode.LITE)

    assert [entry.title for entry in results] == ["гьул - яблоко", "сад - гьул"]


def test_lite_search_uses_position_bonus_for_translation_tokens() -> None:
    """В простом режиме более ранний токен перевода должен ранжироваться выше."""
    service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(
                InMemoryRepository(
                    [
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="слово-1",
                            translation="нужное второе",
                        ),
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="слово-2",
                            translation="первое нужное",
                        ),
                    ]
                )
            ),
        )
    )

    results = service.search("нужное", SearchMode.LITE)

    assert [entry.title for entry in results] == [
        "слово-1 - нужное второе",
        "слово-2 - первое нужное",
    ]


def test_complex_search_finds_example_match() -> None:
    """Комплексный режим должен искать по примерам."""
    service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(
                InMemoryRepository(
                    [
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="аIа",
                            translation="дом",
                            examples=("высокий терем",),
                        )
                    ]
                )
            ),
        )
    )

    results = service.search("терем", SearchMode.COMPLEX)

    assert [entry.title for entry in results] == ["аIа - дом"]


def test_complex_search_prefers_word_prefix_over_comment_noise() -> None:
    """Комплексный режим должен поднимать префикс слова выше шумных совпадений в комментариях."""
    service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(
                InMemoryRepository(
                    [
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="гьул",
                            translation="яблоко",
                        ),
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="сад",
                            translation="яблоко",
                            comments="гьу гьу гьу",
                        ),
                    ]
                )
            ),
        )
    )

    results = service.search("гьу", SearchMode.COMPLEX)

    assert [entry.title for entry in results] == ["гьул - яблоко", "сад - яблоко"]


def test_complex_search_prefers_phrase_match_over_scattered_tokens() -> None:
    """Комплексный режим должен выше ранжировать точную фразу, чем разрозненные токены."""
    service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(
                InMemoryRepository(
                    [
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="аIа",
                            translation="большой дом",
                        ),
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="хъулан",
                            translation="дом",
                            examples=("большой сад рядом",),
                        ),
                    ]
                )
            ),
        )
    )

    results = service.search("большой дом", SearchMode.COMPLEX)

    assert [entry.title for entry in results] == ["аIа - большой дом", "хъулан - дом"]


def test_complex_search_ignores_substring_inside_single_token() -> None:
    """Комплексный режим не должен считать совпадением подстроку внутри отдельного токена."""
    service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(
                InMemoryRepository(
                    [
                        DictionaryEntry(
                            source=DictionarySource.CORE,
                            word="аIа",
                            translation="домик",
                        )
                    ]
                )
            ),
        )
    )

    assert service.search("дом", SearchMode.COMPLEX) == []


def test_complex_search_drops_semantic_noise_when_fuzzy_match_exists() -> None:
    """Сильный fuzzy-матч должен отсекать низкосигнальный semantic-мусор по опечатке."""
    fuzzy_provider = LexicalSearchProvider(
        InMemoryRepository(
            [
                DictionaryEntry(
                    source=DictionarySource.CORE,
                    word="салам",
                    translation="привет",
                )
            ]
        )
    )
    semantic_provider = StaticSearchProvider(
        [
            SearchMatch(
                entry=DictionaryEntry(
                    source=DictionarySource.CORE,
                    word="узданзиб",
                    translation="вольный",
                ),
                score=72,
                origin="semantic",
            )
        ]
    )
    service = DictionarySearchService(providers=(fuzzy_provider, semantic_provider))

    results = service.search("првет", SearchMode.COMPLEX)

    assert [entry.title for entry in results] == ["салам - привет"]


def test_complex_search_boosts_entries_supported_by_both_providers() -> None:
    """Связка lexical и semantic совпадений должна поднимать статью
    выше одиночного semantic-матча.
    """
    shared_entry = DictionaryEntry(
        source=DictionarySource.CORE,
        word="салам",
        translation="привет",
    )
    stronger_semantic_entry = DictionaryEntry(
        source=DictionarySource.CORE,
        word="мастер",
        translation="серебро",
    )
    service = DictionarySearchService(
        providers=(
            StaticSearchProvider(
                [
                    SearchMatch(entry=shared_entry, score=100, origin="lexical"),
                    SearchMatch(entry=stronger_semantic_entry, score=30, origin="lexical"),
                ]
            ),
            StaticSearchProvider(
                [
                    SearchMatch(entry=shared_entry, score=42, origin="semantic"),
                    SearchMatch(entry=stronger_semantic_entry, score=92, origin="semantic"),
                ]
            ),
        )
    )

    results = service.search("что говорят при встрече", SearchMode.COMPLEX)

    assert [entry.title for entry in results] == ["салам - привет", "мастер - серебро"]
