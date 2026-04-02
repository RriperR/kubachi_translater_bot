"""Форматирование словарных статей для Telegram."""

from __future__ import annotations

from models import DictionaryEntry


def format_entry(entry: DictionaryEntry) -> str:
    """Подготовить словарную статью к отправке в Telegram.

    Args:
        entry: Словарная статья, которую нужно превратить в текстовое сообщение.

    Returns:
        Отформатированный многострочный текст статьи.
    """
    lines: list[str] = []

    if entry.banner:
        lines.append(entry.banner)
        lines.append("")

    lines.append(entry.title)

    if entry.examples:
        lines.append("")
        lines.extend(entry.examples)

    extra_lines = list(entry.notes)
    if entry.comments:
        extra_lines.append(entry.comments)

    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    return "\n".join(line.rstrip() for line in lines).strip()
