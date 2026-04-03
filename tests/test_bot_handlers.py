"""Тесты вспомогательных методов Telegram-обработчиков."""

from __future__ import annotations

from bot.handlers import DictionaryBotHandlers
from models import TelegramUser


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
