"""Интеграционные тесты живого PostgreSQL-стека."""

from __future__ import annotations

from psycopg2.extras import RealDictCursor

from config import load_config
from models import DictionaryEntry, DictionarySource, SearchMode
from repositories.db_repository import PostgresRepository
from repositories.postgres import PostgresDictionaryRepository
from services.rag import HashEmbeddingProvider
from services.rag.retrieval import PgvectorSearchProvider
from services.search import DictionarySearchService, LexicalSearchProvider


def _count_rows(repository: PostgresRepository, query: str) -> int:
    """Посчитать строки по SQL-запросу."""
    with repository._connect() as connection, connection.cursor() as cursor:  # noqa: SLF001
        cursor.execute(query)
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def _fetch_entry_id(
    repository: PostgresDictionaryRepository,
    entry: DictionaryEntry,
) -> int:
    """Найти идентификатор записи по ее точному заголовку."""
    with repository._connect() as connection, connection.cursor() as cursor:  # noqa: SLF001
        cursor.execute(
            """
            SELECT id
            FROM dictionary_entries
            WHERE source = %s
              AND word = %s
              AND translation = %s
            """,
            (entry.source.value, entry.word, entry.translation),
        )
        row = cursor.fetchone()
    if row is None:
        raise AssertionError("Inserted dictionary entry was not found in PostgreSQL")
    return int(row[0])


def _delete_entry(repository: PostgresDictionaryRepository, entry_id: int) -> None:
    """Удалить тестовую словарную запись вместе с дочерними сущностями."""
    with repository._connect() as connection, connection.cursor() as cursor:  # noqa: SLF001
        cursor.execute("DELETE FROM dictionary_entries WHERE id = %s", (entry_id,))
        connection.commit()


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
                'dictionary_entry_examples',
                'dictionary_entry_notes',
                'dictionary_entry_comments',
                'dictionary_entry_chunks',
                'dictionary_chunk_embeddings'
              )
            """,
        )
        == 6
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


def test_live_pgvector_search_can_retrieve_inserted_chunk() -> None:
    """pgvector retrieval должен находить только что вставленный чанк без шума."""
    config = load_config()
    repository = PostgresDictionaryRepository(config.database, source=DictionarySource.CORE)
    embedding_provider = HashEmbeddingProvider(dimensions=config.rag_embedding_dimensions)
    entry = DictionaryEntry(
        source=DictionarySource.CORE,
        word="ИНТЕГРАЦИОННЫЙ_ТЕСТ",
        translation="уникальный текст для проверки pgvector retrieval",
        examples=("ИНТЕГРАЦИОННЫЙ_ТЕСТ - уникальный текст для проверки pgvector retrieval",),
        notes=("контекст для integration test",),
        comments="проверка живой индексации",
    )

    repository.import_entries([entry])
    entry_id = _fetch_entry_id(repository, entry)
    try:
        with (
            repository._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):  # noqa: SLF001
            cursor.execute(
                """
                SELECT id, normalized_chunk_text
                FROM dictionary_entry_chunks
                WHERE entry_id = %s
                ORDER BY chunk_type, chunk_order, id
                """,
                (entry_id,),
            )
            chunk_rows = cursor.fetchall()

        assert chunk_rows

        repository.store_chunk_embeddings(
            items=[
                (
                    int(row["id"]),
                    embedding_provider.embed(str(row["normalized_chunk_text"])).to_pgvector(),
                )
                for row in chunk_rows
            ],
            provider=embedding_provider.provider_name,
            model=embedding_provider.model_name,
            version=embedding_provider.version,
            dimensions=embedding_provider.dimensions,
        )

        retrieval = PgvectorSearchProvider(
            repository=repository,
            embedding_provider=embedding_provider,
            top_k=5,
            max_distance=0.75,
        )
        matches = retrieval.search(entry.title, SearchMode.COMPLEX)

        assert matches
        assert matches[0].entry.word == entry.word
        assert matches[0].entry.translation == entry.translation
    finally:
        _delete_entry(repository, entry_id)


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
