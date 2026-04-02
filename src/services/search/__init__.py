"""Пакет поисковых провайдеров и форматирования."""

from __future__ import annotations

from models import DictionaryEntry, DictionarySource, SearchMatch, SearchMode

from .formatting import format_entry
from .lexical import (
    CandidateEntryRepository,
    EntryRepository,
    LexicalSearchProvider,
    SearchProvider,
)
from .orchestrator import DictionarySearchService

__all__ = [
    "DictionaryEntry",
    "DictionarySource",
    "CandidateEntryRepository",
    "DictionarySearchService",
    "EntryRepository",
    "LexicalSearchProvider",
    "SearchMatch",
    "SearchMode",
    "SearchProvider",
    "format_entry",
]
