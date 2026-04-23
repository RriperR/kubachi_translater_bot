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


class SuggestionFlow(StatesGroup):
    """Состояние диалога для отправки идеи или предложения."""

    text = State()


class ScoreAliasFlow(StatesGroup):
    """Состояние диалога для настройки имени в таблице лучших."""

    name = State()


class AdminBroadcastFlow(StatesGroup):
    """Состояния админской рассылки."""

    days = State()
    text = State()
    confirm = State()


class AdminEntriesFlow(StatesGroup):
    """Состояния просмотра и редактирования пользовательских статей."""

    filter_value = State()
    browse = State()
    edit_value = State()
    delete_confirm = State()


class AdminCommentsFlow(StatesGroup):
    """Состояния просмотра комментариев."""

    filter_value = State()
    browse = State()
    delete_confirm = State()


class AdminSuggestionsFlow(StatesGroup):
    """Состояния просмотра пользовательских предложений."""

    browse = State()
