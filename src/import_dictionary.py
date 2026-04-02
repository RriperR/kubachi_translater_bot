"""Одноразовый импорт словаря из CSV в PostgreSQL."""

from __future__ import annotations

from pathlib import Path

from config import load_config
from models import DictionarySource
from repositories.csv_repository import MAIN_SCHEMA, USER_SCHEMA, CsvDictionaryRepository
from repositories.db_repository import PostgresRepository
from repositories.postgres_dictionary_repository import PostgresDictionaryRepository

BASE_DIR = Path(__file__).resolve().parent


def run() -> None:
    """Импортировать основной и пользовательский словари из CSV в PostgreSQL."""
    config = load_config()
    db_repository = PostgresRepository(
        config.database,
        rag_vector_dimensions=config.rag_embedding_dimensions,
    )
    db_repository.ensure_schema()

    main_csv_repository = CsvDictionaryRepository(
        BASE_DIR / "Slovar_14_08.csv",
        DictionarySource.CORE,
        MAIN_SCHEMA,
    )
    user_csv_repository = CsvDictionaryRepository(
        BASE_DIR / "users_translates.csv",
        DictionarySource.USER,
        USER_SCHEMA,
    )
    main_repository = PostgresDictionaryRepository(config.database, DictionarySource.CORE)
    user_repository = PostgresDictionaryRepository(config.database, DictionarySource.USER)

    main_inserted = main_repository.import_entries(main_csv_repository.list_entries())
    user_inserted = user_repository.import_entries(user_csv_repository.list_entries())

    print(f"Импортировано основных статей: {main_inserted}")
    print(f"Импортировано пользовательских статей: {user_inserted}")


def main() -> None:
    """Синхронная точка входа для локального запуска импорта."""
    run()


if __name__ == "__main__":
    main()
