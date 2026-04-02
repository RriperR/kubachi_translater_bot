"""Интеграционные тесты живого PostgreSQL-стека."""

from __future__ import annotations

from config import load_config
from models import DictionarySource, SearchMode
from repositories.db_repository import PostgresRepository
from repositories.postgres import PostgresDictionaryRepository
from services.search import DictionarySearchService, LexicalSearchProvider


def _count_rows(repository: PostgresRepository, query: str) -> int:
    """Посчитать строки по SQL-запросу."""
    with repository._connect() as connection:  # noqa: SLF001
        with connection.cursor() as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def test_schema_is_ready_and_core_tables_exist() -> None:
    """Схема должна быть поднята Alembic-миграциями и содержать словарные таблицы."""
    config = load_config()
    repository = PostgresRepository(config.database)
    repository.require_schema()

    assert (
        _count_rows(
            repository,
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN (
                'dictionary_entries',
                'dictionary_contributors',
                'dictionary_entry_examples',
                'dictionary_entry_notes',
                'dictionary_entry_comments',
                'dictionary_entry_chunks',
                'dictionary_chunk_embeddings'
              )
            """,
        )
        == 7
    )


def test_live_dictionary_search_finds_known_entry() -> None:
    """Локальный поиск на реальной БД должен находить ожидаемую статью."""
    config = load_config()
    service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(
                PostgresDictionaryRepository(config.database, source=DictionarySource.CORE)
            ),
            LexicalSearchProvider(
                PostgresDictionaryRepository(config.database, source=DictionarySource.USER)
            ),
        )
    )

    results = service.search("привет", SearchMode.LITE)

    assert results
    assert any("САЛАМ" in entry.title for entry in results[:5])


def test_embeddings_are_ready_for_live_dictionary() -> None:
    """У словаря должны быть готовые embeddings для retrieval-слоя."""
    config = load_config()
    core_repository = PostgresDictionaryRepository(config.database, source=DictionarySource.CORE)

    assert (
        core_repository.count_pending_rag_chunks(
            provider=config.rag_embedding_provider,
            model=config.rag_embedding_model,
            version="v1",
            dimensions=config.rag_embedding_dimensions,
        )
        == 0
    )
    assert (
        _count_rows(
            core_repository,
            """
            SELECT COUNT(*)
            FROM dictionary_chunk_embeddings
            WHERE embedding_status = 'ready'
              AND embedding IS NOT NULL
            """,
        )
        > 0
    )
