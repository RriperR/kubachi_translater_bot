"""Состояния диалогов Telegram-бота."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddEntryFlow(StatesGroup):
    """Состояния диалога для добавления пользовательской статьи."""

    word = State()
    translation = State()
    phrases = State()
    supporting = State()
    confirm = State()


class CommentFlow(StatesGroup):
    """Состояние диалога для добавления комментария."""

    text = State()
