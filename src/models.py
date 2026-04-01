"""Доменные модели приложения."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class ChatSession:
    """Сессионные данные чата для пагинации результатов."""

    pending_results: list[str] = field(default_factory=list)
