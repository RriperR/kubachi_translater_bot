"""RAG-подсистема словарного бота."""

from __future__ import annotations

from config import AppConfig

from .embeddings.base import EmbeddingProvider, EmbeddingVector
from .embeddings.hash_provider import HashEmbeddingProvider
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


__all__ = [
    "DictionaryRagIndexer",
    "EmbeddingProvider",
    "EmbeddingVector",
    "HashEmbeddingProvider",
    "PgvectorSearchProvider",
    "SentenceTransformerEmbeddingProvider",
    "build_embedding_provider",
]
