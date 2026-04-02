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
_CYRILLIC_TOKEN_RE = re.compile(r"[а-яё-]+")
_RUSSIAN_STEM_SUFFIXES = (
    "ениями",
    "аниями",
    "иями",
    "ями",
    "ами",
    "ениях",
    "аниях",
    "иях",
    "ах",
    "ях",
    "ением",
    "анием",
    "ения",
    "ания",
    "ению",
    "анию",
    "ение",
    "аний",
    "ений",
    "остью",
    "ости",
    "ость",
    "ыми",
    "ими",
    "ого",
    "его",
    "ому",
    "ему",
    "ый",
    "ий",
    "ой",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ую",
    "юю",
    "ом",
    "ем",
    "ам",
    "ям",
    "ов",
    "ев",
    "у",
    "ю",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "о",
    "ь",
)


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


def russian_stem(token: str) -> str:
    """Получить упрощенную основу русского токена для поиска по словоформам.

    Args:
        token: Нормализованный или произвольный токен.

    Returns:
        Укороченная основа русского слова. Для некириллических токенов
        возвращается нормализованное исходное значение.
    """
    normalized = normalize_query(token)
    if not normalized or _CYRILLIC_TOKEN_RE.fullmatch(normalized) is None:
        return normalized

    for suffix in _RUSSIAN_STEM_SUFFIXES:
        if not normalized.endswith(suffix):
            continue
        stem = normalized[: -len(suffix)]
        if len(stem) >= 4:
            return stem
    return normalized


def stem_tokens(text: str) -> tuple[str, ...]:
    """Разбить строку на токены и привести русские слова к упрощенным основам.

    Args:
        text: Исходный текст для токенизации.

    Returns:
        Кортеж stem-токенов без пустых значений.
    """
    return tuple(stem for stem in (russian_stem(token) for token in tokenize(text)) if stem)


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
