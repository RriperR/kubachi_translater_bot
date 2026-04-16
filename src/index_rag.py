"""Принудительная переиндексация chunk-эмбеддингов для pgvector."""

from __future__ import annotations

import logging

from config import load_config
from models import DictionarySource
from repositories.db_repository import PostgresRepository
from repositories.postgres import PostgresDictionaryRepository
from services.rag.factory import build_embedding_provider
from services.rag.indexer import DictionaryRagIndexer


def run() -> None:
    """Переиндексировать все pending-чанки словаря."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    db_repository = PostgresRepository(config.database)
    db_repository.require_schema()

    repositories = (
        PostgresDictionaryRepository(config.database, DictionarySource.CORE),
        PostgresDictionaryRepository(config.database, DictionarySource.USER),
    )
    indexer = DictionaryRagIndexer(
        repositories,
        build_embedding_provider(config),
        batch_size=config.rag_index_batch_size,
    )
    indexed = indexer.sync_pending()
    print(f"Проиндексировано чанков: {indexed}")


def main() -> None:
    """Синхронная точка входа для ручной переиндексации."""
    run()


if __name__ == "__main__":
    main()
