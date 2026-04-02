"""Embedding provider поверх sentence-transformers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .base import EmbeddingVector

_SENTENCE_TRANSFORMER_PROVIDER = "sentence-transformers"
_SENTENCE_TRANSFORMER_VERSION = "v1"


class SentenceTransformerEmbeddingProvider:
    """Embedding provider поверх sentence-transformers."""

    provider_name = _SENTENCE_TRANSFORMER_PROVIDER
    version = _SENTENCE_TRANSFORMER_VERSION

    def __init__(
        self,
        model_name: str,
        dimensions: int,
        batch_size: int,
        device: str,
    ) -> None:
        """Сохранить настройки локальной embedding-модели.

        Args:
            model_name: Идентификатор модели в Hugging Face Hub.
            dimensions: Ожидаемая размерность embeddings.
            batch_size: Размер inference-пакета для `encode`.
            device: Устройство для расчета embeddings, например `cpu`.
        """
        self.model_name = model_name
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._device = device
        self._model: Any | None = None

    @property
    def dimensions(self) -> int:
        """Вернуть размерность embeddings модели.

        Returns:
            Число координат в векторе этой модели.
        """
        return self._dimensions

    def embed(self, text: str) -> EmbeddingVector:
        """Построить embedding одного текста.

        Args:
            text: Текст запроса или чанка.

        Returns:
            Embedding-вектор заданной размерности.
        """
        embeddings = self.embed_many((text,))
        return embeddings[0]

    def embed_many(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Построить embeddings для набора текстов пакетно.

        Args:
            texts: Последовательность текстов для индексации или поиска.

        Returns:
            Embedding-векторы в исходном порядке.

        Raises:
            ValueError: Если модель вернула неожиданную размерность.
        """
        if not texts:
            return []

        model = self._get_model()
        raw_embeddings = model.encode(
            list(texts),
            batch_size=self._batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        vectors: list[EmbeddingVector] = []
        for raw_embedding in raw_embeddings:
            values = tuple(float(value) for value in raw_embedding.tolist())
            vector = EmbeddingVector(values)
            if vector.dimensions != self._dimensions:
                raise ValueError(
                    "Размерность embeddings модели не совпадает с конфигурацией: "
                    f"expected={self._dimensions}, actual={vector.dimensions}"
                )
            vectors.append(vector)
        return vectors

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Пакет sentence-transformers не установлен. "
                "Установите зависимости проекта перед запуском RAG."
            ) from exc

        self._model = SentenceTransformer(self.model_name, device=self._device)
        return self._model
