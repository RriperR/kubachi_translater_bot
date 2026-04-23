"""Доступ к PostgreSQL для пользователей, журнала действий и admin panel."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DatabaseConfig
from models import (
    AdminStats,
    AdminSuggestion,
    BroadcastAudience,
    BroadcastDeliveryStatus,
    BroadcastDeliveryTarget,
    BroadcastProgress,
    BroadcastRecipient,
    BroadcastRecord,
    BroadcastStatus,
    ScoreBoard,
    ScoreEntry,
    ScoreNamePolicy,
    SearchMode,
    TelegramUser,
    UserProfileStats,
)


class PostgresRepository:
    """Репозиторий для работы с таблицами приложения в PostgreSQL."""

    _EXPECTED_SCHEMA_REVISION = "20260423_0014"

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

            for table_name in ("dictionary_entries", "suggestions", "broadcasts"):
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

    def log_action(
        self,
        action: str,
        chat_id: int,
        *,
        action_type: str | None = None,
    ) -> None:
        """Сохранить действие пользователя в журнале.

        Args:
            action: Текст действия для журнала.
            chat_id: Идентификатор чата пользователя.
            action_type: Структурированный тип действия.
        """
        action_text = action.strip()[:1024]
        resolved_action_type = action_type or (
            "command" if action_text.startswith("/") else "search"
        )
        now_utc = datetime.now(timezone.utc)
        searches_delta = 1 if resolved_action_type in {"search", "not_found"} else 0
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM users WHERE chatid = %s", (str(chat_id),))
                user = cursor.fetchone()
                if not user:
                    return
                cursor.execute(
                    """
                    INSERT INTO actions (
                        action,
                        action_type,
                        created_at,
                        fk_user
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        action_text,
                        resolved_action_type,
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
                if searches_delta:
                    cursor.execute(
                        """
                        UPDATE users
                        SET searches_count = searches_count + %s
                        WHERE id = %s
                        """,
                        (searches_delta, user["id"]),
                    )
            connection.commit()

    def log_search_query(self, query: str, chat_id: int, found: bool) -> None:
        """Сохранить поисковый запрос в журнале для admin-статистики.

        Args:
            query: Текст поискового запроса.
            chat_id: Идентификатор чата пользователя.
            found: `True`, если по запросу были результаты.
        """
        self.log_action(
            query,
            chat_id,
            action_type="search" if found else "not_found",
        )

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
        suggestion_text = text.strip()
        if not suggestion_text:
            raise ValueError("Текст предложения не должен быть пустым")
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
                    RETURNING id
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
                cursor.execute(
                    """
                    UPDATE users
                    SET suggestions_count = suggestions_count + 1
                    WHERE id = %s
                    """,
                    (db_user["id"],),
                )
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

    def fetch_broadcast_recipients_all(self) -> list[BroadcastRecipient]:
        """Получить всех пользователей бота для рассылки.

        Returns:
            Полный список пользователей бота.
        """
        return self._fetch_recipients(
            """
            SELECT id, chatid, username, firstname, lastname
            FROM users
            ORDER BY id
            """
        )

    def fetch_broadcast_recipients_active(self, days: int) -> list[BroadcastRecipient]:
        """Получить пользователей, активных за последние N дней.

        Args:
            days: Размер окна активности в днях.

        Returns:
            Список пользователей, у которых была активность в заданном окне.
        """
        return self._fetch_recipients(
            """
            SELECT id, chatid, username, firstname, lastname
            FROM users
            WHERE updated_at >= NOW() - (%s || ' days')::interval
            ORDER BY id
            """,
            (days,),
        )

    def fetch_broadcast_recipients_with_actions(self) -> list[BroadcastRecipient]:
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
                SELECT DISTINCT
                    users.id,
                    users.chatid,
                    users.username,
                    users.firstname,
                    users.lastname
                FROM users
                JOIN actions ON actions.fk_user = users.id
                ORDER BY users.id
                """
            )
            rows = cursor.fetchall()
        return [self._row_to_broadcast_recipient(row) for row in rows]

    def create_broadcast(
        self,
        created_by_chat_id: int,
        audience: BroadcastAudience,
        audience_days: int | None,
        source_chat_id: int,
        source_message_ids: list[int],
        text_preview: str,
        content_type: str,
        recipients: list[BroadcastRecipient],
    ) -> int:
        """Создать задачу рассылки и зафиксировать снимок получателей.

        Args:
            created_by_chat_id: Chat ID администратора, запускающего рассылку.
            audience: Тип аудитории рассылки.
            audience_days: Размер окна активности в днях для выборки активных пользователей.
            source_chat_id: Чат, из которого копируется исходное сообщение.
            source_message_ids: Идентификаторы исходных сообщений для copy_message/copy_messages.
            text_preview: Короткий текст или подпись рассылки для админского интерфейса.
            content_type: Тип контента, например `текст`, `фото` или `файл`.
            recipients: Снимок адресатов на момент запуска.

        Returns:
            Идентификатор созданной рассылки.

        Raises:
            ValueError: Если список исходных сообщений пуст.
            RuntimeError: Если запись рассылки не удалось создать.
        """
        if not source_message_ids:
            raise ValueError("У рассылки должен быть хотя бы один исходный message_id")
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id FROM users WHERE chatid = %s",
                    (str(created_by_chat_id),),
                )
                author_row = cursor.fetchone()
                created_by = int(author_row["id"]) if author_row is not None else None

                cursor.execute(
                    """
                    INSERT INTO broadcasts (
                        created_by,
                        audience_type,
                        audience_days,
                        source_chat_id,
                        text_preview,
                        content_type,
                        status,
                        total_recipients
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        created_by,
                        audience.value,
                        audience_days,
                        source_chat_id,
                        text_preview,
                        content_type,
                        BroadcastStatus.DRAFT.value,
                        len(recipients),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Не удалось создать рассылку")
                broadcast_id = int(row["id"])

                for position, source_message_id in enumerate(source_message_ids):
                    cursor.execute(
                        """
                        INSERT INTO broadcast_source_messages (
                            broadcast_id,
                            position,
                            source_message_id
                        )
                        VALUES (%s, %s, %s)
                        """,
                        (broadcast_id, position, source_message_id),
                    )

                for recipient in recipients:
                    cursor.execute(
                        """
                        INSERT INTO broadcast_deliveries (
                            broadcast_id,
                            user_id,
                            chat_id,
                            status
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            broadcast_id,
                            recipient.user_id,
                            recipient.chat_id,
                            BroadcastDeliveryStatus.PENDING.value,
                        ),
                    )
            connection.commit()
        return broadcast_id

    def fetch_broadcast(self, broadcast_id: int) -> BroadcastRecord | None:
        """Получить сохранённую задачу рассылки.

        Args:
            broadcast_id: Идентификатор рассылки.

        Returns:
            Описание рассылки или `None`, если запись не найдена.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    id,
                    created_by,
                    audience_type,
                    audience_days,
                    source_chat_id,
                    text_preview,
                    content_type,
                    status,
                    total_recipients,
                    sent_count,
                    blocked_count,
                    retry_count,
                    failed_count
                FROM broadcasts
                WHERE id = %s
                """,
                (broadcast_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                """
                SELECT source_message_id
                FROM broadcast_source_messages
                WHERE broadcast_id = %s
                ORDER BY position
                """,
                (broadcast_id,),
            )
            source_rows = cursor.fetchall()
        return BroadcastRecord(
            broadcast_id=int(row["id"]),
            created_by_user_id=int(row["created_by"]) if row["created_by"] is not None else None,
            audience=BroadcastAudience(str(row["audience_type"])),
            audience_days=int(row["audience_days"]) if row["audience_days"] is not None else None,
            source_chat_id=int(row["source_chat_id"]),
            source_message_ids=tuple(
                int(source_row["source_message_id"]) for source_row in source_rows
            ),
            text_preview=str(row["text_preview"] or ""),
            content_type=str(row["content_type"]),
            status=BroadcastStatus(str(row["status"])),
            total_recipients=int(row["total_recipients"] or 0),
            sent_count=int(row["sent_count"] or 0),
            blocked_count=int(row["blocked_count"] or 0),
            retry_count=int(row["retry_count"] or 0),
            failed_count=int(row["failed_count"] or 0),
        )

    def mark_broadcast_running(self, broadcast_id: int) -> None:
        """Перевести рассылку в состояние выполнения.

        Args:
            broadcast_id: Идентификатор рассылки.
        """
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE broadcasts
                    SET status = %s,
                        started_at = COALESCE(started_at, NOW()),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (BroadcastStatus.RUNNING.value, broadcast_id),
                )
            connection.commit()

    def fetch_broadcast_delivery_targets(
        self,
        broadcast_id: int,
        statuses: tuple[BroadcastDeliveryStatus, ...],
    ) -> list[BroadcastDeliveryTarget]:
        """Получить адресатов сохранённой рассылки по набору статусов.

        Args:
            broadcast_id: Идентификатор рассылки.
            statuses: Допустимые статусы доставки для выборки.

        Returns:
            Список адресатов, которым требуется отправка или повторная отправка.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT id, broadcast_id, user_id, chat_id, attempts
                FROM broadcast_deliveries
                WHERE broadcast_id = %s
                  AND status = ANY(%s)
                ORDER BY id
                """,
                (broadcast_id, [status.value for status in statuses]),
            )
            rows = cursor.fetchall()
        return [
            BroadcastDeliveryTarget(
                delivery_id=int(row["id"]),
                broadcast_id=int(row["broadcast_id"]),
                user_id=int(row["user_id"]) if row["user_id"] is not None else None,
                chat_id=int(row["chat_id"]),
                attempts=int(row["attempts"] or 0),
            )
            for row in rows
        ]

    def mark_broadcast_delivery(
        self,
        delivery_id: int,
        status: BroadcastDeliveryStatus,
        *,
        error_text: str | None = None,
        telegram_message_id: int | None = None,
        next_retry_at: datetime | None = None,
    ) -> None:
        """Обновить результат доставки одному получателю.

        Args:
            delivery_id: Идентификатор записи доставки.
            status: Итоговый статус попытки.
            error_text: Краткое описание ошибки, если доставка не удалась.
            telegram_message_id: Идентификатор созданного Telegram-сообщения.
            next_retry_at: Момент, после которого запись можно пробовать снова.
        """
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE broadcast_deliveries
                    SET status = %s,
                        attempts = attempts + 1,
                        last_error = %s,
                        telegram_message_id = %s,
                        sent_at = CASE
                            WHEN %s = %s THEN NOW()
                            ELSE sent_at
                        END,
                        last_attempt_at = NOW(),
                        next_retry_at = %s
                    WHERE id = %s
                    """,
                    (
                        status.value,
                        error_text,
                        telegram_message_id,
                        status.value,
                        BroadcastDeliveryStatus.SENT.value,
                        next_retry_at,
                        delivery_id,
                    ),
                )
            connection.commit()

    def finalize_broadcast(self, broadcast_id: int) -> BroadcastProgress:
        """Пересчитать статистику рассылки и сохранить финальный статус.

        Args:
            broadcast_id: Идентификатор рассылки.

        Returns:
            Обновлённая агрегированная сводка по рассылке.
        """
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = %s) AS sent_count,
                        COUNT(*) FILTER (WHERE status = %s) AS blocked_count,
                        COUNT(*) FILTER (WHERE status = %s) AS retry_count,
                        COUNT(*) FILTER (WHERE status = %s) AS failed_count,
                        COUNT(*) FILTER (WHERE status = %s) AS pending_count,
                        COUNT(*) AS total_recipients
                    FROM broadcast_deliveries
                    WHERE broadcast_id = %s
                    """,
                    (
                        BroadcastDeliveryStatus.SENT.value,
                        BroadcastDeliveryStatus.BLOCKED.value,
                        BroadcastDeliveryStatus.RETRY.value,
                        BroadcastDeliveryStatus.FAILED.value,
                        BroadcastDeliveryStatus.PENDING.value,
                        broadcast_id,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    row = {
                        "sent_count": 0,
                        "blocked_count": 0,
                        "retry_count": 0,
                        "failed_count": 0,
                        "pending_count": 0,
                        "total_recipients": 0,
                    }
                retry_like_count = int(row["retry_count"] or 0) + int(row["failed_count"] or 0)
                pending_count = int(row["pending_count"] or 0)
                final_status = (
                    BroadcastStatus.COMPLETED
                    if retry_like_count == 0 and pending_count == 0
                    else BroadcastStatus.COMPLETED_WITH_ERRORS
                )
                cursor.execute(
                    """
                    UPDATE broadcasts
                    SET status = %s,
                        updated_at = NOW(),
                        completed_at = NOW(),
                        total_recipients = %s,
                        sent_count = %s,
                        blocked_count = %s,
                        retry_count = %s,
                        failed_count = %s
                    WHERE id = %s
                    """,
                    (
                        final_status.value,
                        int(row["total_recipients"] or 0),
                        int(row["sent_count"] or 0),
                        int(row["blocked_count"] or 0),
                        int(row["retry_count"] or 0),
                        int(row["failed_count"] or 0),
                        broadcast_id,
                    ),
                )
            connection.commit()
        return BroadcastProgress(
            broadcast_id=broadcast_id,
            status=final_status,
            total_recipients=int(row["total_recipients"] or 0),
            sent_count=int(row["sent_count"] or 0),
            blocked_count=int(row["blocked_count"] or 0),
            retry_count=int(row["retry_count"] or 0),
            failed_count=int(row["failed_count"] or 0),
            pending_count=int(row["pending_count"] or 0),
        )

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
                "SELECT COALESCE(SUM(searches_count), 0) FROM users",
            )
            top_queries = self._fetch_query_stats(cursor, action_type="search")
            failed_queries = self._fetch_query_stats(cursor, action_type="not_found")
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

    def fetch_user_profile_stats(self, chat_id: int) -> UserProfileStats | None:
        """Собрать краткую персональную статистику пользователя.

        Args:
            chat_id: Идентификатор Telegram-чата пользователя.

        Returns:
            Сводка по пользователю или `None`, если запись не найдена.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    id,
                    chatid,
                    username,
                    firstname,
                    lastname,
                    mode,
                    created_at,
                    updated_at,
                    searches_count,
                    user_entries_count,
                    comments_count,
                    suggestions_count
                FROM users
                WHERE chatid = %s
                """,
                (str(chat_id),),
            )
            user_row = cursor.fetchone()
            if user_row is None:
                return None

        return UserProfileStats(
            user=TelegramUser(
                chat_id=int(str(user_row["chatid"])),
                username=(
                    str(user_row["username"]) if user_row.get("username") is not None else None
                ),
                first_name=str(user_row.get("firstname") or ""),
                last_name=str(user_row.get("lastname") or ""),
            ),
            mode=SearchMode.from_value(user_row.get("mode")),
            created_at=user_row["created_at"],
            last_activity_at=user_row["updated_at"],
            searches_count=int(user_row.get("searches_count") or 0),
            user_entries_count=int(user_row.get("user_entries_count") or 0),
            comments_count=int(user_row.get("comments_count") or 0),
            suggestions_count=int(user_row.get("suggestions_count") or 0),
        )

    def fetch_scoreboard(self, chat_id: int, limit: int = 10) -> ScoreBoard:
        """Собрать таблицы лучших по пользовательским счётчикам.

        Args:
            chat_id: Идентификатор Telegram-чата текущего пользователя.
            limit: Число строк в каждом рейтинге.

        Returns:
            Таблицы лучших и личные места текущего пользователя вне топа.
        """
        categories = {
            "searches": "searches_count",
            "user_entries": "user_entries_count",
            "comments": "comments_count",
            "suggestions": "suggestions_count",
        }
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            category_rows = {
                category: self._fetch_score_rows(cursor, counter_column, chat_id, limit)
                for category, counter_column in categories.items()
            }

        parsed = {
            category: tuple(
                self._row_to_score_entry(row, chat_id, personal=False)
                for row in rows
                if not bool(row.get("is_personal"))
            )
            for category, rows in category_rows.items()
        }
        personal = {
            category: next(
                (
                    self._row_to_score_entry(row, chat_id, personal=True)
                    for row in rows
                    if bool(row.get("is_personal"))
                ),
                None,
            )
            for category, rows in category_rows.items()
        }
        return ScoreBoard(
            searches=parsed["searches"],
            user_entries=parsed["user_entries"],
            comments=parsed["comments"],
            suggestions=parsed["suggestions"],
            personal_searches=personal["searches"],
            personal_user_entries=personal["user_entries"],
            personal_comments=personal["comments"],
            personal_suggestions=personal["suggestions"],
        )

    def update_score_display_name(
        self,
        chat_id: int,
        policy: ScoreNamePolicy,
        custom_name: str | None,
    ) -> None:
        """Обновить публичную настройку имени для таблицы лучших.

        Args:
            chat_id: Идентификатор Telegram-чата пользователя.
            policy: Способ отображения имени.
            custom_name: Пользовательский псевдоним для политики `custom`.
        """
        stored_custom_name = custom_name if policy == ScoreNamePolicy.CUSTOM else None
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET score_name_policy = %s,
                        score_custom_name = %s,
                        updated_at = NOW()
                    WHERE chatid = %s
                    """,
                    (policy.value, stored_custom_name, str(chat_id)),
                )
            connection.commit()

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
        """Обновить режим поиска пользователя.

        Args:
            chat_id: Идентификатор Telegram-чата пользователя.
            mode: Новый режим поиска.
        """
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

    def _fetch_recipients(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> list[BroadcastRecipient]:
        """Выполнить запрос и преобразовать строки в получателей рассылки.

        Args:
            query: SQL-запрос, возвращающий данные пользователя.
            params: Параметры SQL-запроса.

        Returns:
            Подготовленный список адресатов рассылки.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(query, params)
            rows = cursor.fetchall()
        return [self._row_to_broadcast_recipient(row) for row in rows]

    @staticmethod
    def _fetch_score_rows(
        cursor: Any,
        counter_column: str,
        chat_id: int,
        limit: int,
    ) -> list[dict[str, object]]:
        allowed_columns = {
            "searches_count",
            "user_entries_count",
            "comments_count",
            "suggestions_count",
        }
        if counter_column not in allowed_columns:
            raise ValueError("Недопустимая колонка рейтинга")

        query = """
            WITH ranked AS (
                SELECT
                    id,
                    chatid,
                    username,
                    firstname,
                    lastname,
                    score_name_policy,
                    score_custom_name,
                    __COUNTER_COLUMN__ AS value,
                    ROW_NUMBER() OVER (ORDER BY __COUNTER_COLUMN__ DESC, id ASC) AS rank
                FROM users
                WHERE __COUNTER_COLUMN__ > 0
            )
            SELECT
                id,
                chatid,
                username,
                firstname,
                lastname,
                score_name_policy,
                score_custom_name,
                value,
                rank,
                FALSE AS is_personal
            FROM ranked
            WHERE rank <= %s
            UNION ALL
            SELECT
                id,
                chatid,
                username,
                firstname,
                lastname,
                score_name_policy,
                score_custom_name,
                value,
                rank,
                TRUE AS is_personal
            FROM ranked
            WHERE chatid = %s
              AND rank > %s
            ORDER BY rank
            """.replace("__COUNTER_COLUMN__", counter_column)
        cursor.execute(
            query,
            (limit, str(chat_id), limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_user(row: dict[str, object]) -> TelegramUser:
        """Преобразовать строку результата в доменную модель пользователя.

        Args:
            row: Словарь со столбцами SQL-запроса.

        Returns:
            Объект пользователя Telegram.
        """
        return TelegramUser(
            chat_id=int(str(row["chatid"])),
            username=str(row["username"]) if row.get("username") is not None else None,
            first_name=str(row.get("firstname") or ""),
            last_name=str(row.get("lastname") or ""),
        )

    @classmethod
    def _row_to_broadcast_recipient(cls, row: dict[str, object]) -> BroadcastRecipient:
        """Преобразовать строку результата в получателя рассылки.

        Args:
            row: Словарь со столбцами SQL-запроса.

        Returns:
            Получатель рассылки с user_id и данными Telegram-пользователя.
        """
        return BroadcastRecipient(
            user_id=int(str(row["id"])),
            user=cls._row_to_user(row),
        )

    @classmethod
    def _row_to_score_entry(
        cls,
        row: dict[str, object],
        chat_id: int,
        *,
        personal: bool,
    ) -> ScoreEntry:
        display_name = (
            "Вы"
            if personal
            else cls._format_score_display_name(
                user_id=int(str(row["id"])),
                policy=ScoreNamePolicy(str(row.get("score_name_policy") or "anonymous")),
                custom_name=str(row.get("score_custom_name") or ""),
                username=str(row["username"]) if row.get("username") is not None else None,
                first_name=str(row.get("firstname") or ""),
                last_name=str(row.get("lastname") or ""),
            )
        )
        return ScoreEntry(
            rank=int(str(row["rank"])),
            value=int(str(row["value"])),
            display_name=display_name,
            is_current_user=str(row["chatid"]) == str(chat_id),
        )

    @staticmethod
    def _format_score_display_name(
        user_id: int,
        policy: ScoreNamePolicy,
        custom_name: str,
        username: str | None,
        first_name: str,
        last_name: str,
    ) -> str:
        anonymous_name = f"Участник #{user_id}"
        if policy == ScoreNamePolicy.CUSTOM and custom_name:
            return custom_name
        if policy == ScoreNamePolicy.TELEGRAM:
            if username:
                return f"@{username}"
            full_name = " ".join(part for part in (first_name, last_name) if part).strip()
            if full_name:
                return full_name
        return anonymous_name

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
    def _fetch_query_stats(
        cursor: Any,
        action_type: str,
    ) -> tuple[tuple[str, int], ...]:
        cursor.execute(
            """
            SELECT action AS query, COUNT(*) AS hits
            FROM actions
            WHERE action_type = %s
            GROUP BY action
            ORDER BY hits DESC, query ASC
            LIMIT 10
            """,
            (action_type,),
        )
        rows = cursor.fetchall()
        return tuple((str(row["query"]), int(row["hits"])) for row in rows)
