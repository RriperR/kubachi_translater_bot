"""FastAPI-приложение отдельного embedding-сервиса."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from config import AppConfig
from services.rag import build_local_embedding_provider
from services.rag.embeddings.base import EmbeddingProvider


class EmbedRequest(BaseModel):
    """Запрос на embedding одного текста."""

    text: str = Field(min_length=1)


class EmbedManyRequest(BaseModel):
    """Запрос на embeddings для набора текстов."""

    texts: list[str]


class EmbeddingServiceApp:
    """Контейнер зависимостей embedding-сервиса."""

    def __init__(self, config: AppConfig) -> None:
        """Собрать локальный provider для HTTP-сервиса.

        Args:
            config: Корневая конфигурация приложения.
        """
        self._config = config
        self._provider = build_local_embedding_provider(config)
        self.app = self._create_app()

    @property
    def provider(self) -> EmbeddingProvider:
        """Вернуть локальный embedding provider сервиса.

        Returns:
            Настроенный локальный provider embeddings.
        """
        return self._provider

    def _create_app(self) -> FastAPI:
        app = FastAPI(title="Kubachi Embedding Service", version="1.0.0")
        provider = self._provider

        @app.get("/health")
        def health() -> dict[str, str]:
            """Проверить, что сервис поднят.

            Returns:
                Короткий статус health-check.
            """
            return {"status": "ok"}

        @app.get("/v1/metadata")
        def metadata() -> dict[str, str | int]:
            """Вернуть метаданные активной embedding-модели.

            Returns:
                Имя провайдера, модель, версия и размерность.
            """
            return {
                "provider_name": provider.provider_name,
                "model_name": provider.model_name,
                "version": provider.version,
                "dimensions": provider.dimensions,
            }

        @app.post("/v1/embed")
        def embed(payload: EmbedRequest) -> dict[str, list[float]]:
            """Построить embedding одного текста.

            Args:
                payload: JSON с одним текстом.

            Returns:
                JSON с одним embedding-вектором.
            """
            vector = provider.embed(payload.text)
            return {"embedding": list(vector.values)}

        @app.post("/v1/embed-many")
        def embed_many(payload: EmbedManyRequest) -> dict[str, list[list[float]]]:
            """Построить embeddings для нескольких текстов.

            Args:
                payload: JSON с массивом текстов.

            Returns:
                JSON с массивом embedding-векторов.
            """
            vectors = provider.embed_many(payload.texts)
            return {"embeddings": [list(vector.values) for vector in vectors]}

        return app
