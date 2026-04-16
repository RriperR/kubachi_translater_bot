"""Тесты вспомогательных методов Telegram-обработчиков."""

from __future__ import annotations

from datetime import datetime

from bot.application import DictionaryBotApp
from bot.handlers import DictionaryBotHandlers
from models import SearchMode, TelegramUser, UserProfileStats


def test_build_suggestion_notification_contains_actor_and_text() -> None:
    """Уведомление о предложении должно содержать автора, chat_id и сам текст идеи."""
    actor = TelegramUser(
        chat_id=123456,
        username="tester",
        first_name="Иван",
        last_name="Петров",
    )

    notification = DictionaryBotHandlers._build_suggestion_notification(
        actor,
        "Добавить отдельный режим для предложений пользователей.",
    )

    assert '@tester "Иван Петров" (chat_id=123456)' in notification
    assert "Добавить отдельный режим для предложений пользователей." in notification


def test_build_user_profile_summary_contains_main_fields() -> None:
    """Команда `/me` должна показывать режим и основную активность пользователя."""
    profile = UserProfileStats(
        user=TelegramUser(
            chat_id=123456,
            username="tester",
            first_name="Иван",
            last_name="Петров",
        ),
        mode=SearchMode.COMPLEX,
        created_at=datetime(2026, 4, 3, 10, 0),
        last_activity_at=datetime(2026, 4, 3, 12, 30),
        searches_count=14,
        user_entries_count=2,
        comments_count=3,
        suggestions_count=1,
    )

    summary = DictionaryBotHandlers._build_user_profile_summary(
        profile,
        reference_dt=datetime(2026, 4, 10, 9, 0),
    )

    assert "👤 Ваш профиль" in summary
    assert "123456" in summary
    assert "🔎 Режим поиска: расширенный" in summary
    assert "03.04.2026 (7 дней)" in summary
    assert "Поисков: 14" in summary
    assert "Статей добавлено: 2" in summary
    assert "Комментариев: 3" in summary
    assert "Предложений: 1" in summary
    assert summary.strip().endswith("chat_id: 123456")
    assert "@tester" not in summary
    assert "Последняя активность" not in summary


def test_build_default_commands_contains_main_user_actions() -> None:
    """Меню обычного пользователя должно содержать основные понятные команды."""
    commands = DictionaryBotApp._build_default_commands()

    assert [command.command for command in commands] == [
        "start",
        "help",
        "info",
        "mode",
        "me",
        "add",
        "comment",
        "suggest",
    ]
    assert [command.description for command in commands] == [
        "Начать заново",
        "Что умеет бот",
        "Как пользоваться ботом",
        "Настроить поиск",
        "Мой профиль",
        "Предложить новый перевод",
        "Комментарий к статье",
        "Идея или замечание",
    ]


def test_build_admin_commands_extends_default_commands() -> None:
    """Меню администратора должно включать пользовательские команды и админские пункты."""
    commands = DictionaryBotApp._build_admin_commands()

    assert [command.command for command in commands][-2:] == ["admin", "chatid"]
    assert [command.description for command in commands][-2:] == [
        "Открыть админку",
        "Показать chat_id",
    ]
