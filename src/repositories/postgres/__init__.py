"""PostgreSQL-репозитории словаря."""

from __future__ import annotations

from .base import PostgresRepositoryBase
from .dictionary_rag_repository import DictionaryRagRepositoryMixin
from .dictionary_repository import DictionaryRepositoryMixin
from .dictionary_search_repository import DictionarySearchRepositoryMixin


class PostgresDictionaryRepository(
    DictionaryRepositoryMixin,
    DictionarySearchRepositoryMixin,
    DictionaryRagRepositoryMixin,
):
    """Полный PostgreSQL-репозиторий словарных статей."""


__all__ = [
    "DictionaryRagRepositoryMixin",
    "DictionaryRepositoryMixin",
    "DictionarySearchRepositoryMixin",
    "PostgresDictionaryRepository",
    "PostgresRepositoryBase",
]
