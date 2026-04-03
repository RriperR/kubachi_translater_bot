"""Доменные модели приложения."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SearchMode(str, Enum):
    """Режим поиска по словарю."""

    LITE = "lite"
    COMPLEX = "complex"

    @classmethod
    def from_value(cls, value: str | None) -> SearchMode:
        """Преобразовать строковое значение в режим поиска.

        Args:
            value: Значение режима поиска из базы данных или callback.

        Returns:
            Выбранный режим поиска. Неизвестные значения приводятся к `LITE`.
        """
        if value == cls.COMPLEX.value:
            return cls.COMPLEX
        return cls.LITE


class DictionarySource(str, Enum):
    """Источник словарной статьи."""

    CORE = "core"
    USER = "user"


class BroadcastAudience(str, Enum):
    """Сегмент аудитории для промо-рассылки."""

    ALL = "all"
    ACTIVE_DAYS = "active_days"
    WITH_ACTIONS = "with_actions"


@dataclass(frozen=True)
class TelegramUser:
    """Сведения о пользователе Telegram, нужные приложению."""

    chat_id: int
    username: str | None
    first_name: str
    last_name: str = ""


@dataclass(frozen=True)
class DictionaryEntry:
    """Нормализованная словарная статья."""

    source: DictionarySource
    word: str
    translation: str
    examples: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    comments: str = ""
    contributor_username: str | None = None
    contributor_first_name: str | None = None
    contributor_last_name: str | None = None
    banner: str | None = None

    @property
    def title(self) -> str:
        """Вернуть заголовок статьи в формате `слово - перевод`.

        Returns:
            Короткий заголовок статьи для показа в интерфейсе и поиске.
        """
        return f"{self.word} - {self.translation}"


@dataclass(frozen=True)
class UserSubmittedEntry:
    """Словарная статья, предложенная пользователем."""

    word: str
    translation: str
    phrases_raw: str
    supporting_raw: str
    contributor: TelegramUser


@dataclass(frozen=True)
class SearchMatch:
    """Результат поиска с вычисленным score."""

    entry: DictionaryEntry
    score: int
    origin: str = "lexical"


@dataclass(frozen=True)
class RagChunkRecord:
    """Чанк словаря, ожидающий индексации эмбеддингом."""

    chunk_id: int
    entry_id: int
    source: DictionarySource
    chunk_type: str
    chunk_text: str
    normalized_chunk_text: str
    content_hash: str


@dataclass(frozen=True)
class SemanticSearchCandidate:
    """Кандидат, найденный семантическим поиском по chunk-эмбеддингам."""

    entry: DictionaryEntry
    chunk_id: int
    chunk_type: str
    chunk_text: str
    distance: float


@dataclass
class ChatSession:
    """Сессионные данные чата для пагинации результатов."""

    pending_results: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AdminSuggestion:
    """Предложение пользователя для админки."""

    suggestion_id: int
    text: str
    created_at: datetime
    status: str
    author: TelegramUser


@dataclass(frozen=True)
class AdminUserEntryRecord:
    """Пользовательская словарная статья с метаданными автора."""

    entry_id: int
    entry: DictionaryEntry
    created_at: datetime
    author: TelegramUser | None


@dataclass(frozen=True)
class AdminCommentRecord:
    """Комментарий к словарной статье с метаданными автора."""

    comment_id: int
    entry_id: int
    entry_title: str
    comment_text: str
    created_at: datetime
    author: TelegramUser | None


@dataclass(frozen=True)
class AdminStats:
    """Сводная статистика для admin panel."""

    total_users: int
    new_users_day: int
    new_users_week: int
    new_users_month: int
    active_users_day: int
    active_users_week: int
    active_users_month: int
    total_searches: int
    top_queries: tuple[tuple[str, int], ...] = ()
    failed_queries: tuple[tuple[str, int], ...] = ()
    user_entries_count: int = 0
    comments_count: int = 0
    suggestions_count: int = 0


@dataclass(frozen=True)
class UserProfileStats:
    """Краткая сводка по пользователю для команды `/me`."""

    user: TelegramUser
    mode: SearchMode
    created_at: datetime
    last_activity_at: datetime
    searches_count: int = 0
    user_entries_count: int = 0
    comments_count: int = 0
    suggestions_count: int = 0
