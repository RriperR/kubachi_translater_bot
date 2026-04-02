"""Локальный deterministic embedding provider для RAG."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Sequence

from normalization import tokenize

from .base import EmbeddingVector

_HASH_EMBEDDING_PROVIDER = "local"
_HASH_EMBEDDING_MODEL = "hash-embedding"
_HASH_EMBEDDING_VERSION = "v1"


class HashEmbeddingProvider:
    """Локальный детерминированный embedder без внешнего API."""

    provider_name = _HASH_EMBEDDING_PROVIDER
    model_name = _HASH_EMBEDDING_MODEL
    version = _HASH_EMBEDDING_VERSION

    def __init__(self, dimensions: int = 256) -> None:
        """Сохранить размерность эмбеддингов.

        Args:
            dimensions: Размерность результирующего вектора.
        """
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        """Вернуть размерность embeddings этого провайдера.

        Returns:
            Число координат в выходном embedding-векторе.
        """
        return self._dimensions

    def embed(self, text: str) -> EmbeddingVector:
        """Построить эмбеддинг строки.

        Args:
            text: Текст чанка или запроса.

        Returns:
            Нормализованный вектор фиксированной размерности.
        """
        buckets = [0.0] * self._dimensions
        for token in self._iter_features(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:4], byteorder="big") % self._dimensions
            sign = -1.0 if digest[4] % 2 else 1.0
            weight = 0.35 if token.startswith("tri:") else 1.0
            buckets[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0:
            return EmbeddingVector(tuple(0.0 for _ in range(self._dimensions)))

        return EmbeddingVector(tuple(value / norm for value in buckets))

    def embed_many(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Построить embeddings для набора текстов.

        Args:
            texts: Последовательность текстов для индексации.

        Returns:
            Список embedding-векторов в исходном порядке.
        """
        return [self.embed(text) for text in texts]

    @staticmethod
    def _iter_features(text: str) -> Iterable[str]:
        tokens = tokenize(text)
        for token in tokens:
            yield f"tok:{token}"
            for trigram in HashEmbeddingProvider._char_ngrams(token, size=3):
                yield f"tri:{trigram}"

        for left, right in zip(tokens, tokens[1:], strict=False):
            yield f"bi:{left}_{right}"

    @staticmethod
    def _char_ngrams(token: str, size: int) -> Iterable[str]:
        if len(token) <= size:
            yield token
            return
        for index in range(len(token) - size + 1):
            yield token[index : index + size]
