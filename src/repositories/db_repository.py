"""Доступ к PostgreSQL для пользователей и журнала действий."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DatabaseConfig
from models import SearchMode, TelegramUser


class PostgresRepository:
    """Репозиторий для работы с таблицами приложения в PostgreSQL."""

    def __init__(self, config: DatabaseConfig) -> None:
        """Сохранить параметры подключения к базе данных.

        Args:
            config: Настройки подключения к PostgreSQL.
        """
        self._config = config

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

    def require_schema(self) -> None:
        """Проверить, что схема уже создана через Alembic.

        Raises:
            RuntimeError: Если миграции еще не применены.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT to_regclass('public.alembic_version') AS table_name
                """
            )
            table_row = cursor.fetchone()
            if table_row is None or table_row["table_name"] is None:
                raise RuntimeError(self._schema_error_message())
            cursor.execute(
                """
                SELECT version_num
                FROM alembic_version
                LIMIT 1
                """
            )
            version_row = cursor.fetchone()
            if version_row is None:
                raise RuntimeError(self._schema_error_message())
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'dictionary_entries'
                """
            )
            if cursor.fetchone() is None:
                raise RuntimeError(self._schema_error_message())

    @staticmethod
    def _schema_error_message() -> str:
        return (
            "Схема PostgreSQL не инициализирована. Примените миграции командой `make db-upgrade`."
        )

    def ensure_user(self, user: TelegramUser) -> None:
        """Создать пользователя в базе, если его еще нет.

        Args:
            user: Пользователь Telegram, для которого создается запись.
        """
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM users WHERE chatid = %s", (str(user.chat_id),))
                if cursor.fetchone():
                    return
                cursor.execute(
                    """
                    INSERT INTO users (username, firstname, lastname, chatid, mode)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        user.username,
                        user.first_name,
                        user.last_name,
                        str(user.chat_id),
                        SearchMode.LITE.value,
                    ),
                )
            connection.commit()

    def log_action(self, action: str, chat_id: int) -> None:
        """Сохранить действие пользователя в журнале.

        Args:
            action: Текст действия для журнала.
            chat_id: Идентификатор чата пользователя.
        """
        short_action = action[:32]
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM users WHERE chatid = %s", (str(chat_id),))
                user = cursor.fetchone()
                if not user:
                    return
                cursor.execute(
                    """
                    INSERT INTO actions (action, date_time, fk_user)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        short_action,
                        (datetime.utcnow() + timedelta(hours=3)).isoformat(
                            sep=" ", timespec="seconds"
                        ),
                        user["id"],
                    ),
                )
            connection.commit()

    def get_user_mode(self, chat_id: int) -> SearchMode:
        """Получить текущий режим поиска пользователя.

        Args:
            chat_id: Идентификатор чата пользователя.

        Returns:
            Режим поиска пользователя или `LITE`, если запись не найдена.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute("SELECT mode FROM users WHERE chatid = %s", (str(chat_id),))
            user = cursor.fetchone()
            if not user:
                return SearchMode.LITE
            return SearchMode.from_value(user.get("mode"))

    def update_user_mode(self, chat_id: int, mode: SearchMode) -> None:
        """Обновить режим поиска пользователя.

        Args:
            chat_id: Идентификатор чата пользователя.
            mode: Новый режим поиска, который нужно сохранить.
        """
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET mode = %s WHERE chatid = %s",
                    (mode.value, str(chat_id)),
                )
            connection.commit()

    def fetch_users(self) -> list[dict[str, object]]:
        """Выгрузить все строки из таблицы пользователей.

        Returns:
            Список записей таблицы `users`.
        """
        return self._fetch_table("SELECT * FROM users ORDER BY id")

    def fetch_actions(self) -> list[dict[str, object]]:
        """Выгрузить все строки из таблицы действий.

        Returns:
            Список записей таблицы `actions`.
        """
        return self._fetch_table("SELECT * FROM actions ORDER BY id")

    def _fetch_table(self, query: str) -> list[dict[str, object]]:
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(query)
            rows = cursor.fetchall()
        return [dict(row) for row in rows]
