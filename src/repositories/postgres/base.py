"""Базовые помощники для PostgreSQL-репозиториев словаря."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg2

from config import DatabaseConfig
from models import DictionarySource
from normalization import tokenize


class PostgresRepositoryBase:
    """База для репозиториев, работающих с PostgreSQL."""

    _USER_COUNTER_COLUMNS = frozenset(
        {
            "searches_count",
            "suggestions_count",
            "comments_count",
            "user_entries_count",
        }
    )
    _USER_COUNTER_QUERIES = {
        "searches_count": """
            UPDATE users
            SET searches_count = GREATEST(searches_count + %s, 0)
            WHERE id = %s
        """,
        "suggestions_count": """
            UPDATE users
            SET suggestions_count = GREATEST(suggestions_count + %s, 0)
            WHERE id = %s
        """,
        "comments_count": """
            UPDATE users
            SET comments_count = GREATEST(comments_count + %s, 0)
            WHERE id = %s
        """,
        "user_entries_count": """
            UPDATE users
            SET user_entries_count = GREATEST(user_entries_count + %s, 0)
            WHERE id = %s
        """,
    }

    def __init__(self, config: DatabaseConfig, source: DictionarySource) -> None:
        """Сохранить параметры подключения и закрепленный источник.

        Args:
            config: Настройки подключения к PostgreSQL.
            source: Источник словарных статей, закрепленный за репозиторием.
        """
        self._config = config
        self._source = source

    @property
    def source(self) -> DictionarySource:
        """Вернуть словарный источник, закрепленный за репозиторием.

        Returns:
            Источник статей, с которым работает этот экземпляр репозитория.
        """
        return self._source

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        connection: Any = psycopg2.connect(
            host=self._config.host,
            port=self._config.port,
            user=self._config.user,
            password=self._config.password.get_secret_value(),
            dbname=self._config.database,
        )
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _normalize_token_text(text: str) -> str:
        """Нормализовать текст по токенам.

        Args:
            text: Исходный текст.

        Returns:
            Текст, собранный из нормализованных токенов.
        """
        return " ".join(tokenize(text))

    @staticmethod
    def _strip_text(value: object | None) -> str | None:
        """Подчистить строковое значение и убрать пустые строки.

        Args:
            value: Исходное значение.

        Returns:
            Обрезанная строка или `None`.
        """
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def sync_rag_chunks(self) -> int:
        """Синхронизировать RAG-чанки.

        Returns:
            Число сохраненных чанков.

        Raises:
            NotImplementedError: Если конкретный репозиторий не реализовал RAG-слой.
        """
        raise NotImplementedError

    def _adjust_user_counter(
        self,
        cursor: Any,
        user_id: int | None,
        column: str,
        delta: int,
    ) -> None:
        """Изменить числовой счётчик пользователя.

        Args:
            cursor: Открытый PostgreSQL-курсор.
            user_id: Идентификатор пользователя.
            column: Имя столбца-счётчика в `users`.
            delta: На сколько нужно изменить значение.

        Raises:
            ValueError: Если передан неподдерживаемый счётчик.
        """
        if user_id is None or delta == 0:
            return
        if column not in self._USER_COUNTER_COLUMNS:
            raise ValueError(f"Неподдерживаемый счётчик пользователя: {column}")

        cursor.execute(self._USER_COUNTER_QUERIES[column], (delta, user_id))

    def _decrement_comment_counters_for_entry(self, cursor: Any, entry_id: int) -> None:
        """Уменьшить число комментариев у авторов удаляемой статьи.

        Args:
            cursor: Открытый PostgreSQL-курсор.
            entry_id: Идентификатор удаляемой статьи.
        """
        cursor.execute(
            """
            WITH deleted_comment_counts AS (
                SELECT user_id, COUNT(*) AS comments_count
                FROM dictionary_entry_comments
                WHERE entry_id = %s
                  AND user_id IS NOT NULL
                GROUP BY user_id
            )
            UPDATE users
            SET comments_count = GREATEST(
                users.comments_count - deleted_comment_counts.comments_count,
                0
            )
            FROM deleted_comment_counts
            WHERE users.id = deleted_comment_counts.user_id
            """,
            (entry_id,),
        )

    def _fetch_entry_rows(
        self,
        query_name: str,
        parameters: tuple[object, ...],
        limit: int | None = None,
        cursor: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Получить строки словарных статей.

        Args:
            query_name: Имя SQL-шаблона выборки.
            parameters: Параметры для SQL-запроса.
            limit: Ограничение на количество строк.
            cursor: Уже открытый курсор PostgreSQL, если он есть.

        Returns:
            Список словарных строк из PostgreSQL.

        Raises:
            NotImplementedError: Если конкретный репозиторий не реализовал поисковый слой.
        """
        raise NotImplementedError

    def _fetch_entry_row(self, entry_id: int, cursor: Any) -> dict[str, Any] | None:
        """Получить одну строку словарной статьи.

        Args:
            entry_id: Идентификатор статьи.
            cursor: Уже открытый курсор PostgreSQL.

        Returns:
            Строка статьи или `None`, если запись не найдена.

        Raises:
            NotImplementedError: Если конкретный репозиторий не реализовал поисковый слой.
        """
        raise NotImplementedError

    def _row_to_entry(self, row: dict[str, Any]) -> Any:
        """Преобразовать строку БД в доменную статью.

        Args:
            row: Строка PostgreSQL с данными статьи.

        Returns:
            Доменная модель статьи.

        Raises:
            NotImplementedError: Если конкретный репозиторий не реализовал поисковый слой.
        """
        raise NotImplementedError

    def _sync_rag_chunks_for_entry(self, cursor: Any, entry_id: int) -> int:
        """Синхронизировать RAG-чанки для одной статьи.

        Args:
            cursor: Уже открытый курсор PostgreSQL.
            entry_id: Идентификатор статьи.

        Returns:
            Количество чанков, записанных для статьи.

        Raises:
            NotImplementedError: Если конкретный репозиторий не реализовал RAG-слой.
        """
        raise NotImplementedError
