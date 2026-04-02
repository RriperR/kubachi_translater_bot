"""Базовые типы для embedding-провайдеров RAG."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingVector:
    """Результат расчета эмбеддинга."""

    values: tuple[float, ...]

    @property
    def dimensions(self) -> int:
        """Вернуть размерность эмбеддинга.

        Returns:
            Число координат в векторе.
        """
        return len(self.values)

    def to_pgvector(self) -> str:
        """Преобразовать вектор в строковый литерал pgvector.

        Returns:
            Строка формата `[0.1,0.2,...]`, пригодная для SQL-вставки.
        """
        serialized = ",".join(f"{value:.8f}" for value in self.values)
        return f"[{serialized}]"


class EmbeddingProvider(Protocol):
    """Контракт провайдера embeddings для индексации и поиска."""

    provider_name: str
    model_name: str
    version: str

    @property
    def dimensions(self) -> int:
        """Вернуть размерность embeddings провайдера.

        Returns:
            Число координат в выходном векторе.
        """
        ...

    def embed(self, text: str) -> EmbeddingVector:
        """Построить embedding одного текста.

        Args:
            text: Текст запроса или чанка.

        Returns:
            Построенный embedding-вектор.
        """
        ...

    def embed_many(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Построить embeddings для нескольких текстов сразу.

        Args:
            texts: Последовательность текстов для пакетной индексации.

        Returns:
            Векторы в том же порядке, что и входные тексты.
        """
        ...
