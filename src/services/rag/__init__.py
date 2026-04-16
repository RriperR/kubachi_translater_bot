"""RAG-подсистема словарного бота."""

from __future__ import annotations

from .embeddings.base import EmbeddingProvider, EmbeddingVector
from .embeddings.hash_provider import HashEmbeddingProvider
from .embeddings.http_provider import HttpEmbeddingProvider
from .embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider
from .factory import build_embedding_provider, build_local_embedding_provider
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
