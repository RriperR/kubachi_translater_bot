"""RAG-подсистема словарного бота."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .embeddings.base import EmbeddingProvider, EmbeddingVector
from .embeddings.hash_provider import HashEmbeddingProvider
from .embeddings.http_provider import HttpEmbeddingProvider
from .embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider
from .factory import build_embedding_provider, build_local_embedding_provider

if TYPE_CHECKING:
    from .indexer import DictionaryRagIndexer
    from .retrieval import PgvectorSearchProvider

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


def __getattr__(name: str) -> Any:
    """Лениво импортировать тяжелые части RAG-пакета.

    Args:
        name: Имя экспортируемого объекта.

    Returns:
        Запрошенный объект пакета.

    Raises:
        AttributeError: Если имя не экспортируется этим пакетом.
    """
    if name == "DictionaryRagIndexer":
        from .indexer import DictionaryRagIndexer

        return DictionaryRagIndexer
    if name == "PgvectorSearchProvider":
        from .retrieval import PgvectorSearchProvider

        return PgvectorSearchProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
