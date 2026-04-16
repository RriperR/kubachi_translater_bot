"""Точка входа для отдельного HTTP embedding-сервиса."""

from __future__ import annotations

import logging

import uvicorn

from config import load_config
from embedding_service.app import EmbeddingServiceApp


def main() -> None:
    """Поднять локальный HTTP-сервис embeddings."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    service = EmbeddingServiceApp(config)
    uvicorn.run(
        service.app,
        host=config.embedding_service_host,
        port=config.embedding_service_port,
    )


if __name__ == "__main__":
    main()
