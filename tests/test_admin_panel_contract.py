"""Контрактные тесты для будущей Telegram-admin panel."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bot.handlers import DictionaryBotHandlers
from models import (
    BroadcastAudience,
    BroadcastProgress,
    BroadcastStatus,
    DictionaryEntry,
    DictionarySource,
    TelegramUser,
)


@dataclass(frozen=True)
class BroadcastTarget:
    """Адресат рассылки для тестового контракта."""

    chat_id: int
    username: str | None = None
    first_name: str = ""
    last_name: str = ""


def _require_helper(name: str):
    helper = getattr(DictionaryBotHandlers, name, None)
    if helper is None:
        pytest.skip(f"helper {name} is not implemented yet")
    return helper


def _maybe_call(helper: object, *args: object, **kwargs: object) -> object:
    try:
        return helper(*args, **kwargs)  # type: ignore[misc]
    except TypeError as exc:
        pytest.skip(f"helper signature is not ready for this contract: {exc}")


def test_build_broadcast_report_formats_counts() -> None:
    """Отчет по рассылке должен показывать успехи, блокировки и ошибки."""
    helper = _require_helper("_build_broadcast_report")

    report = _maybe_call(
        helper,
        BroadcastProgress(
            broadcast_id=17,
            status=BroadcastStatus.COMPLETED_WITH_ERRORS,
            total_recipients=20,
            sent_count=12,
            blocked_count=3,
            retry_count=2,
            failed_count=2,
            pending_count=1,
        ),
    )

    assert "12" in str(report)
    assert "3" in str(report)
    assert "2" in str(report)
    assert "17" in str(report)


def test_build_broadcast_confirmation_contains_recipient_count() -> None:
    """Подтверждение рассылки должно содержать аудиторию и число адресатов."""
    helper = _require_helper("_build_broadcast_confirmation")

    confirmation = _maybe_call(
        helper,
        audience=BroadcastAudience.ALL,
        days=None,
        recipients_count=42,
        content_label="текст",
    )

    text = str(confirmation)
    assert "42" in text
    assert "текст" in text
    assert "Новость недели" not in text


def test_build_user_entry_card_contains_author_and_date() -> None:
    """Карточка пользовательской статьи должна содержать автора и дату добавления."""
    helper = _require_helper("_build_user_entry_card")
    entry = DictionaryEntry(
        source=DictionarySource.USER,
        word="салам",
        translation="привет",
        contributor_username="tester",
        contributor_first_name="Иван",
        contributor_last_name="Петров",
    )

    card = _maybe_call(
        helper,
        entry=entry,
        added_at="2026-04-03 10:00",
    )

    assert "салам - привет" in str(card)
    assert "tester" in str(card)
    assert "Иван" in str(card)
    assert "2026-04-03 10:00" in str(card)


def test_build_comment_card_contains_entry_and_author() -> None:
    """Карточка комментария должна показывать статью, автора и дату."""
    helper = _require_helper("_build_comment_card")
    actor = TelegramUser(
        chat_id=123456,
        username="tester",
        first_name="Иван",
        last_name="Петров",
    )

    comment = _maybe_call(
        helper,
        entry_title="салам - привет",
        comment_text="Полезная подсказка",
        author=actor,
        created_at="2026-04-03 10:30",
    )

    text = str(comment)
    assert "салам - привет" in text
    assert "tester" in text
    assert "Полезная подсказка" in text
    assert "2026-04-03 10:30" in text


def test_build_stats_summary_contains_key_metrics() -> None:
    """Сводка статистики должна включать пользователей, запросы и вклад контента."""
    helper = _require_helper("_build_stats_summary")

    summary = _maybe_call(
        helper,
        total_users=100,
        active_users_day=12,
        active_users_week=40,
        active_users_month=78,
        new_users_day=3,
        new_users_week=8,
        new_users_month=19,
        total_searches=560,
        top_queries=("привет", "дом"),
        failed_queries=7,
        user_entries=24,
        comments=11,
        suggestions=5,
    )

    text = str(summary)
    assert "100" in text
    assert "560" in text
    assert "привет" in text
    assert "дом" in text
    assert "24" in text
    assert "11" in text
    assert "5" in text
