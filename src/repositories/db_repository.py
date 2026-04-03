"""Доступ к PostgreSQL для пользователей, журнала действий и admin panel."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DatabaseConfig
from models import AdminStats, AdminSuggestion, SearchMode, TelegramUser


class PostgresRepository:
    """Репозиторий для работы с таблицами приложения в PostgreSQL."""

    _EXPECTED_SCHEMA_REVISION = "20260403_0003"

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
        """Проверить, что схема уже создана и применена нужная миграция.

        Raises:
            RuntimeError: Если база еще не подготовлена нужными миграциями.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute("SELECT to_regclass('public.alembic_version') AS table_name")
            table_row = cursor.fetchone()
            if table_row is None or table_row["table_name"] is None:
                raise RuntimeError(self._schema_error_message())

            cursor.execute("SELECT version_num FROM alembic_version LIMIT 1")
            version_row = cursor.fetchone()
            if (
                version_row is None
                or str(version_row["version_num"]) != self._EXPECTED_SCHEMA_REVISION
            ):
                raise RuntimeError(self._schema_error_message())

            for table_name in ("dictionary_entries", "suggestions"):
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = %s
                    """,
                    (table_name,),
                )
                if cursor.fetchone() is None:
                    raise RuntimeError(self._schema_error_message())

    @staticmethod
    def _schema_error_message() -> str:
        return (
            "Схема PostgreSQL не инициализирована. Примените миграции командой `make db-upgrade`."
        )

    def ensure_user(self, user: TelegramUser) -> None:
        """Создать или обновить пользователя в базе.

        Args:
            user: Пользователь Telegram, для которого создается запись.
        """
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        username,
                        firstname,
                        lastname,
                        chatid,
                        mode,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chatid) DO UPDATE
                    SET username = EXCLUDED.username,
                        firstname = EXCLUDED.firstname,
                        lastname = EXCLUDED.lastname,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        user.username,
                        user.first_name,
                        user.last_name,
                        str(user.chat_id),
                        SearchMode.LITE.value,
                        now,
                        now,
                    ),
                )
            connection.commit()

    def log_action(self, action: str, chat_id: int) -> None:
        """Сохранить действие пользователя в журнале.

        Args:
            action: Текст действия для журнала.
            chat_id: Идентификатор чата пользователя.
        """
        action_text = action.strip()[:1024]
        now_utc = datetime.now(timezone.utc)
        now_local = self._utc_plus_three_now()
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM users WHERE chatid = %s", (str(chat_id),))
                user = cursor.fetchone()
                if not user:
                    return
                cursor.execute(
                    """
                    INSERT INTO actions (action, date_time, created_at, fk_user)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        action_text,
                        now_local.isoformat(sep=" ", timespec="seconds"),
                        now_utc,
                        user["id"],
                    ),
                )
                cursor.execute(
                    """
                    UPDATE users
                    SET updated_at = %s
                    WHERE id = %s
                    """,
                    (now_utc, user["id"]),
                )
            connection.commit()

    def log_search_query(self, query: str, chat_id: int, found: bool) -> None:
        """Сохранить поисковый запрос в журнале для admin-статистики.

        Args:
            query: Текст поискового запроса.
            chat_id: Идентификатор чата пользователя.
            found: `True`, если по запросу были результаты.
        """
        prefix = "SEARCH" if found else "NOTFOUND"
        self.log_action(f"{prefix}: {query}", chat_id)

    def insert_suggestion(self, user: TelegramUser, text: str) -> int:
        """Сохранить пользовательское предложение в базе данных.

        Args:
            user: Автор предложения.
            text: Текст предложения.

        Returns:
            Идентификатор созданной записи.

        Raises:
            RuntimeError: Если пользователя не удалось найти или предложение не сохранилось.
            ValueError: Если текст предложения пустой.
        """
        self.ensure_user(user)
        suggestion_text = text.strip()
        if not suggestion_text:
            raise ValueError("Текст предложения не должен быть пустым")
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM users WHERE chatid = %s", (str(user.chat_id),))
                db_user = cursor.fetchone()
                if db_user is None:
                    raise RuntimeError("Не удалось найти пользователя для сохранения предложения")
                cursor.execute(
                    """
                    INSERT INTO suggestions (fk_user, text, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (db_user["id"], suggestion_text, "new", now, now),
                )
                row = cursor.fetchone()
            connection.commit()
        if row is None:
            raise RuntimeError("Не удалось сохранить предложение")
        return int(row["id"])

    def fetch_suggestions(self, limit: int, offset: int = 0) -> list[AdminSuggestion]:
        """Получить предложения пользователей для админки.

        Args:
            limit: Максимальное число записей.
            offset: Смещение для пагинации.

        Returns:
            Список предложений с авторами.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    suggestions.id,
                    suggestions.text,
                    suggestions.status,
                    suggestions.created_at,
                    users.chatid,
                    users.username,
                    users.firstname,
                    users.lastname
                FROM suggestions
                JOIN users ON users.id = suggestions.fk_user
                ORDER BY suggestions.created_at DESC, suggestions.id DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cursor.fetchall()
        return [
            AdminSuggestion(
                suggestion_id=int(row["id"]),
                text=str(row["text"]),
                status=str(row["status"]),
                created_at=row["created_at"],
                author=TelegramUser(
                    chat_id=int(row["chatid"]),
                    username=row["username"],
                    first_name=str(row["firstname"]),
                    last_name=str(row["lastname"]),
                ),
            )
            for row in rows
        ]

    def fetch_broadcast_recipients_all(self) -> list[TelegramUser]:
        """Получить всех пользователей бота для рассылки.

        Returns:
            Полный список пользователей бота.
        """
        return self._fetch_recipients(
            """
            SELECT chatid, username, firstname, lastname
            FROM users
            ORDER BY id
            """
        )

    def fetch_broadcast_recipients_active(self, days: int) -> list[TelegramUser]:
        """Получить пользователей, активных за последние N дней.

        Args:
            days: Размер окна активности в днях.

        Returns:
            Список пользователей, у которых была активность в заданном окне.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT DISTINCT users.chatid, users.username, users.firstname, users.lastname
                FROM users
                JOIN actions ON actions.fk_user = users.id
                WHERE actions.created_at >= NOW() - (%s || ' days')::interval
                ORDER BY users.id
                """,
                (days,),
            )
            rows = cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    def fetch_broadcast_recipients_with_actions(self) -> list[TelegramUser]:
        """Получить пользователей, у которых есть хотя бы одно действие в журнале.

        Returns:
            Список пользователей, оставивших хотя бы одно действие.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT DISTINCT users.chatid, users.username, users.firstname, users.lastname
                FROM users
                JOIN actions ON actions.fk_user = users.id
                ORDER BY users.id
                """
            )
            rows = cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    def fetch_admin_stats(self) -> AdminStats:
        """Собрать агрегированную статистику для админки.

        Returns:
            Сводка по пользователям, запросам и пользовательскому контенту.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            total_users = self._scalar(cursor, "SELECT COUNT(*) FROM users")
            new_users_day = self._scalar(
                cursor,
                "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '1 day'",
            )
            new_users_week = self._scalar(
                cursor,
                "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days'",
            )
            new_users_month = self._scalar(
                cursor,
                "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '30 days'",
            )
            active_users_day = self._scalar(
                cursor,
                "SELECT COUNT(*) FROM users WHERE updated_at >= NOW() - INTERVAL '1 day'",
            )
            active_users_week = self._scalar(
                cursor,
                "SELECT COUNT(*) FROM users WHERE updated_at >= NOW() - INTERVAL '7 days'",
            )
            active_users_month = self._scalar(
                cursor,
                "SELECT COUNT(*) FROM users WHERE updated_at >= NOW() - INTERVAL '30 days'",
            )
            total_searches = self._scalar(
                cursor,
                """
                SELECT COUNT(*)
                FROM actions
                WHERE action LIKE 'SEARCH:%'
                   OR action LIKE 'NOTFOUND:%'
                """,
            )
            top_queries = self._fetch_query_stats(cursor, "SEARCH:%")
            failed_queries = self._fetch_query_stats(cursor, "NOTFOUND:%")
            user_entries_count = self._scalar(
                cursor,
                "SELECT COUNT(*) FROM dictionary_entries WHERE source = 'user'",
            )
            comments_count = self._scalar(cursor, "SELECT COUNT(*) FROM dictionary_entry_comments")
            suggestions_count = self._scalar(cursor, "SELECT COUNT(*) FROM suggestions")

        return AdminStats(
            total_users=total_users,
            new_users_day=new_users_day,
            new_users_week=new_users_week,
            new_users_month=new_users_month,
            active_users_day=active_users_day,
            active_users_week=active_users_week,
            active_users_month=active_users_month,
            total_searches=total_searches,
            top_queries=top_queries,
            failed_queries=failed_queries,
            user_entries_count=user_entries_count,
            comments_count=comments_count,
            suggestions_count=suggestions_count,
        )

    def get_user_mode(self, chat_id: int) -> SearchMode:
        """Получить текущий режим поиска пользователя.

        Args:
            chat_id: Идентификатор чата пользователя.

        Returns:
            Текущий режим поиска пользователя или `LITE`, если запись не найдена.
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
        """Обновить режим поиска пользователя."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET mode = %s,
                        updated_at = NOW()
                    WHERE chatid = %s
                    """,
                    (mode.value, str(chat_id)),
                )
            connection.commit()

    def fetch_users(self) -> list[dict[str, object]]:
        """Выгрузить все строки из таблицы пользователей.

        Returns:
            Список строк таблицы `users`.
        """
        return self._fetch_table("SELECT * FROM users ORDER BY id")

    def fetch_actions(self) -> list[dict[str, object]]:
        """Выгрузить все строки из таблицы действий.

        Returns:
            Список строк таблицы `actions`.
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

    def _fetch_recipients(self, query: str, params: tuple[object, ...] = ()) -> list[TelegramUser]:
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(query, params)
            rows = cursor.fetchall()
        return [self._row_to_user(row) for row in rows]

    @staticmethod
    def _row_to_user(row: dict[str, object]) -> TelegramUser:
        return TelegramUser(
            chat_id=int(str(row["chatid"])),
            username=str(row["username"]) if row.get("username") is not None else None,
            first_name=str(row.get("firstname") or ""),
            last_name=str(row.get("lastname") or ""),
        )

    @staticmethod
    def _scalar(cursor: Any, query: str, params: tuple[object, ...] = ()) -> int:
        cursor.execute(query, params)
        row = cursor.fetchone()
        if row is None:
            return 0
        if isinstance(row, dict):
            return int(next(iter(row.values())))
        return int(row[0])

    @staticmethod
    def _fetch_query_stats(cursor: Any, pattern: str) -> tuple[tuple[str, int], ...]:
        cursor.execute(
            """
            SELECT regexp_replace(action, '^[A-Z]+:\\s*', '') AS query, COUNT(*) AS hits
            FROM actions
            WHERE action LIKE %s
            GROUP BY regexp_replace(action, '^[A-Z]+:\\s*', '')
            ORDER BY hits DESC, query ASC
            LIMIT 10
            """,
            (pattern,),
        )
        rows = cursor.fetchall()
        return tuple((str(row["query"]), int(row["hits"])) for row in rows)

    @staticmethod
    def _utc_plus_three_now() -> datetime:
        return datetime.utcnow() + timedelta(hours=3)
