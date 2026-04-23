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


class ScoreNamePolicy(str, Enum):
    """Политика отображения пользователя в таблице лучших."""

    ANONYMOUS = "anonymous"
    TELEGRAM = "telegram"
    CUSTOM = "custom"


class DictionarySource(str, Enum):
    """Источник словарной статьи."""

    CORE = "core"
    USER = "user"


class BroadcastAudience(str, Enum):
    """Сегмент аудитории для промо-рассылки."""

    ALL = "all"
    ACTIVE_DAYS = "active_days"
    WITH_ACTIONS = "with_actions"


class BroadcastStatus(str, Enum):
    """Состояние задачи рассылки."""

    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"


class BroadcastDeliveryStatus(str, Enum):
    """Состояние доставки конкретному пользователю."""

    PENDING = "pending"
    SENT = "sent"
    BLOCKED = "blocked"
    RETRY = "retry"
    FAILED = "failed"


@dataclass(frozen=True)
class TelegramUser:
    """Сведения о пользователе Telegram, нужные приложению."""

    chat_id: int
    username: str | None
    first_name: str
    last_name: str = ""


@dataclass(frozen=True)
class BroadcastRecipient:
    """Получатель рассылки со ссылкой на запись пользователя."""

    user_id: int
    user: TelegramUser

    @property
    def chat_id(self) -> int:
        """Вернуть chat_id получателя.

        Returns:
            Идентификатор чата Telegram.
        """
        return self.user.chat_id


@dataclass(frozen=True)
class BroadcastRecord:
    """Сохранённая задача рассылки."""

    broadcast_id: int
    created_by_user_id: int | None
    audience: BroadcastAudience
    audience_days: int | None
    source_chat_id: int
    source_message_ids: tuple[int, ...]
    text_preview: str
    content_type: str
    status: BroadcastStatus
    total_recipients: int
    sent_count: int
    blocked_count: int
    retry_count: int
    failed_count: int


@dataclass(frozen=True)
class BroadcastDeliveryTarget:
    """Адресат конкретной доставки внутри сохранённой рассылки."""

    delivery_id: int
    broadcast_id: int
    user_id: int | None
    chat_id: int
    attempts: int


@dataclass(frozen=True)
class BroadcastProgress:
    """Агрегированное состояние выполнения рассылки."""

    broadcast_id: int
    status: BroadcastStatus
    total_recipients: int
    sent_count: int
    blocked_count: int
    retry_count: int
    failed_count: int
    pending_count: int


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
class ScoreEntry:
    """Строка таблицы лучших."""

    rank: int
    value: int
    display_name: str
    is_current_user: bool = False


@dataclass(frozen=True)
class ScoreBoard:
    """Набор таблиц лучших по основным пользовательским действиям."""

    searches: tuple[ScoreEntry, ...]
    user_entries: tuple[ScoreEntry, ...]
    comments: tuple[ScoreEntry, ...]
    suggestions: tuple[ScoreEntry, ...]
    personal_searches: ScoreEntry | None = None
    personal_user_entries: ScoreEntry | None = None
    personal_comments: ScoreEntry | None = None
    personal_suggestions: ScoreEntry | None = None


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
