"""Хранение сессионных данных чатов в памяти."""

from __future__ import annotations

from models import ChatSession


class SessionStore:
    """Простое in-memory хранилище пагинации по чатам."""

    def __init__(self) -> None:
        """Инициализировать пустое хранилище сессий."""
        self._sessions: dict[int, ChatSession] = {}

    def get(self, chat_id: int) -> ChatSession:
        """Вернуть сессию чата, создавая ее при первом обращении.

        Args:
            chat_id: Идентификатор чата в Telegram.

        Returns:
            Объект сессионного состояния для указанного чата.
        """
        if chat_id not in self._sessions:
            self._sessions[chat_id] = ChatSession()
        return self._sessions[chat_id]

    def reset(self, chat_id: int) -> None:
        """Сбросить сессионное состояние чата.

        Args:
            chat_id: Идентификатор чата, для которого очищается состояние.
        """
        self._sessions[chat_id] = ChatSession()
