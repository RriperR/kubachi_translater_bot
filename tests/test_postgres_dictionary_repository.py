"""Тесты нормализации данных для PostgreSQL-репозитория."""

from __future__ import annotations

from repositories.postgres_dictionary_repository import PostgresDictionaryRepository


def test_normalize_token_text_strips_punctuation_between_tokens() -> None:
    """Нормализация токенов должна убирать запятые и сохранять отдельные слова."""
    assert (
        PostgresDictionaryRepository._normalize_token_text("привет, приветствие")
        == "привет приветствие"
    )


def test_build_search_text_uses_token_normalization_for_translation() -> None:
    """Поле полного поиска должно содержать перевод без пунктуации внутри токенов."""
    search_text = PostgresDictionaryRepository._build_search_text(
        word="салам",
        translation="привет, приветствие",
        examples=(),
        notes=(),
        comments="",
    )

    assert search_text == "салам привет приветствие"
