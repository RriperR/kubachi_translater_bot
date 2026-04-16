"""RAG-подсистема словарного бота."""

from .embeddings.base import EmbeddingProvider, EmbeddingVector
from .embeddings.hash_provider import HashEmbeddingProvider
from .embeddings.http_provider import HttpEmbeddingProvider
from .embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider
from .factory import build_embedding_provider, build_local_embedding_provider

__all__ = [
    "EmbeddingProvider",
    "EmbeddingVector",
    "HashEmbeddingProvider",
    "HttpEmbeddingProvider",
    "SentenceTransformerEmbeddingProvider",
    "build_embedding_provider",
    "build_local_embedding_provider",
]
