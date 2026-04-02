"""Тесты нормализации данных для PostgreSQL-репозитория."""

from __future__ import annotations

from pydantic import SecretStr

from config import DatabaseConfig
from models import DictionarySource
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


def test_build_rag_chunks_splits_entry_into_semantic_parts() -> None:
    """RAG-подготовка должна собирать чанки по статье, примерам, заметкам и комментариям."""
    repository = PostgresDictionaryRepository(
        config=DatabaseConfig(
            host="localhost",
            port=5432,
            user="postgres",
            password=SecretStr("secret"),
            database="kubachi",
        ),
        source=DictionarySource.CORE,
    )

    chunks = repository._build_rag_chunks(
        {
            "id": 7,
            "source": "core",
            "word": "салам",
            "translation": "привет, приветствие",
            "examples": ["салам айт", "салам вам"],
            "notes": ["уважительная форма"],
            "comments": "пользовательское уточнение\nвторая строка",
        }
    )

    assert chunks == [
        (
            7,
            "core",
            "title",
            0,
            "салам - привет, приветствие",
            "салам - привет приветствие",
        ),
        (7, "core", "translation", 0, "привет, приветствие", "привет приветствие"),
        (7, "core", "example", 0, "салам айт", "салам айт"),
        (7, "core", "example", 1, "салам вам", "салам вам"),
        (7, "core", "note", 0, "уважительная форма", "уважительная форма"),
        (
            7,
            "core",
            "comment",
            0,
            "пользовательское уточнение",
            "пользовательское уточнение",
        ),
        (7, "core", "comment", 1, "вторая строка", "вторая строка"),
    ]
