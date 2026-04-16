"""RAG-подсистема словарного бота."""

from __future__ import annotations

from config import AppConfig

from .embeddings.base import EmbeddingProvider, EmbeddingVector
from .embeddings.hash_provider import HashEmbeddingProvider
from .embeddings.http_provider import HttpEmbeddingProvider
from .embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider
from .indexer import DictionaryRagIndexer
from .retrieval import PgvectorSearchProvider


def build_embedding_provider(config: AppConfig) -> EmbeddingProvider:
    """Собрать embedding provider из конфигурации приложения.

    Args:
        config: Корневая конфигурация приложения.

    Returns:
        Настроенный провайдер embeddings для поиска и индексации.

    Raises:
        ValueError: Если указан неподдерживаемый тип embedding provider.
    """
    provider_name = config.rag_embedding_provider.strip().lower()
    if provider_name in {"http", "remote"}:
        if not config.rag_embedding_service_url:
            raise ValueError(
                "Для RAG_EMBEDDING_PROVIDER=http нужно задать RAG_EMBEDDING_SERVICE_URL"
            )
        return HttpEmbeddingProvider(
            service_url=config.rag_embedding_service_url,
            timeout_seconds=config.rag_embedding_service_timeout_seconds,
        )
    if provider_name == "hash":
        return HashEmbeddingProvider(dimensions=config.rag_embedding_dimensions)
    if provider_name == "sentence-transformers":
        return SentenceTransformerEmbeddingProvider(
            model_name=config.rag_embedding_model,
            dimensions=config.rag_embedding_dimensions,
            batch_size=config.rag_embedding_batch_size,
            device=config.rag_embedding_device,
        )
    raise ValueError(f"Неподдерживаемый RAG embedding provider: {config.rag_embedding_provider}")


def build_local_embedding_provider(config: AppConfig) -> EmbeddingProvider:
    """Собрать локальный provider для отдельного embedding-сервиса.

    Args:
        config: Корневая конфигурация приложения.

    Returns:
        Локальный embedding provider, работающий внутри отдельного сервиса.

    Raises:
        ValueError: Если указан неподдерживаемый тип локального embedding provider.
    """
    provider_name = config.embedding_service_provider.strip().lower()
    if provider_name == "hash":
        return HashEmbeddingProvider(dimensions=config.embedding_service_dimensions)
    if provider_name == "sentence-transformers":
        return SentenceTransformerEmbeddingProvider(
            model_name=config.embedding_service_model,
            dimensions=config.embedding_service_dimensions,
            batch_size=config.embedding_service_batch_size,
            device=config.embedding_service_device,
        )
    raise ValueError(
        f"Неподдерживаемый EMBEDDING_SERVICE_PROVIDER: {config.embedding_service_provider}"
    )


__all__ = [
    "DictionaryRagIndexer",
    "EmbeddingProvider",
    "EmbeddingVector",
    "HashEmbeddingProvider",
    "HttpEmbeddingProvider",
    "PgvectorSearchProvider",
    "SentenceTransformerEmbeddingProvider",
    "build_embedding_provider",
    "build_local_embedding_provider",
]
