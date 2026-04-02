"""Repository layer."""

from __future__ import annotations

from .postgres import PostgresDictionaryRepository, PostgresRepositoryBase

__all__ = [
    "PostgresDictionaryRepository",
    "PostgresRepositoryBase",
]
