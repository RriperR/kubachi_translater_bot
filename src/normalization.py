"""Нормализация поисковых запросов и словарных текстов."""

from __future__ import annotations

import re
from collections.abc import Iterable

_QUERY_TRANSLATION = str.maketrans(
    {
        "1": "i",
        "!": "i",
        "l": "i",
        "|": "i",
        "I": "i",
    }
)

_WORD_TRANSLATION = str.maketrans(
    {
        "1": "I",
        "!": "I",
        "l": "I",
        "|": "I",
        "i": "I",
    }
)

_PUNCTUATION_RE = re.compile(r"[(){}\[\],.;:!?\"'«»]+")
_MULTISPACE_RE = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """Нормализовать пользовательский запрос для поиска.

    Args:
        text: Исходная строка запроса от пользователя.

    Returns:
        Строка в едином виде: нижний регистр, унифицированные символы и пробелы.
    """
    translated = text.translate(_QUERY_TRANSLATION).lower()
    return _MULTISPACE_RE.sub(" ", translated).strip()


def normalize_kubachi_word(text: str) -> str:
    """Нормализовать кубачинское слово для сохранения.

    Args:
        text: Слово в исходном виде перед сохранением в словарь.

    Returns:
        Строка с приведенными к единому виду символами без крайних пробелов.
    """
    return text.translate(_WORD_TRANSLATION).strip()


def tokenize(text: str) -> tuple[str, ...]:
    """Разбить строку на нормализованные токены.

    Args:
        text: Исходная строка, которую нужно разбить на токены.

    Returns:
        Кортеж токенов без пустых элементов и лишней пунктуации.
    """
    normalized = normalize_query(text)
    cleaned = _PUNCTUATION_RE.sub(" ", normalized)
    return tuple(part for part in cleaned.split() if part)


def split_values(text: str, separator: str) -> tuple[str, ...]:
    """Разделить строку по разделителю и убрать пустые элементы.

    Args:
        text: Исходная строка со значениями.
        separator: Разделитель, по которому строка разбивается на части.

    Returns:
        Кортеж непустых значений без крайних пробелов.
    """
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(separator) if part.strip())


def comma_values(text: str) -> tuple[str, ...]:
    """Вернуть нормализованные значения, разделенные запятыми.

    Args:
        text: Строка со значениями, разделенными запятыми.

    Returns:
        Кортеж значений после разбиения по запятым и нормализации.
    """
    return tuple(normalize_query(part) for part in split_values(text, ","))


def count_occurrences(needle: str, haystack: str) -> int:
    """Подсчитать число вхождений нормализованной подстроки.

    Args:
        needle: Искомая подстрока после нормализации.
        haystack: Текст, в котором нужно считать вхождения.

    Returns:
        Количество вхождений `needle` в нормализованный `haystack`.
    """
    if not needle:
        return 0
    return normalize_query(haystack).count(needle)


def compact_lines(lines: Iterable[str]) -> tuple[str, ...]:
    """Убрать пустые строки и лишние пробелы.

    Args:
        lines: Последовательность строк, подготовленных для очистки.

    Returns:
        Кортеж строк, пригодный для вывода пользователю.
    """
    return tuple(line.strip() for line in lines if line and line.strip())
