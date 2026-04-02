"""Тесты поиска по словарю."""

from __future__ import annotations

from models import DictionaryEntry, DictionarySource, SearchMode
from services.search_service import CsvSearchProvider, DictionarySearchService


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


def test_lite_search_ignores_examples_and_notes() -> None:
    """Простой режим не должен искать по примерам и примечаниям."""
    provider = CsvSearchProvider(
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


def test_lite_search_prefers_word_match_over_translation() -> None:
    """В простом режиме совпадение по слову должно быть выше совпадения по переводу."""
    service = DictionarySearchService(
        providers=(
            CsvSearchProvider(
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
            CsvSearchProvider(
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
            CsvSearchProvider(
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
