"""Тесты обновления пользовательских счётчиков в PostgreSQL-репозитории."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import SecretStr

from config import DatabaseConfig
from models import BroadcastAudience, BroadcastDeliveryStatus, BroadcastRecipient, TelegramUser
from repositories.db_repository import PostgresRepository


class FakeCursor:
    """Простой курсор, запоминающий выполненные запросы и заранее заданные ответы."""

    def __init__(
        self,
        responses: list[dict[str, object] | None],
        many_responses: list[list[dict[str, object]]] | None = None,
    ) -> None:
        """Сохранить очередь ответов для `fetchone`.

        Args:
            responses: Последовательность результатов, которые вернёт `fetchone`.
            many_responses: Последовательность результатов, которые вернёт `fetchall`.
        """
        self._responses = list(responses)
        self._many_responses = list(many_responses or [])
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> FakeCursor:
        """Вернуть курсор для использования в `with`.

        Returns:
            Текущий экземпляр курсора.
        """
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Завершить контекст курсора.

        Args:
            exc_type: Тип исключения.
            exc: Экземпляр исключения.
            traceback: Трассировка исключения.
        """
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        """Запомнить выполненный SQL-запрос.

        Args:
            query: SQL-запрос.
            params: Параметры запроса.
        """
        normalized_query = " ".join(query.split())
        self.executed.append((normalized_query, params))

    def fetchone(self) -> dict[str, object] | None:
        """Вернуть следующий подготовленный результат.

        Returns:
            Следующая строка ответа или `None`.
        """
        if not self._responses:
            return None
        return self._responses.pop(0)

    def fetchall(self) -> list[dict[str, object]]:
        """Вернуть следующий подготовленный набор строк.

        Returns:
            Подготовленный список строк.
        """
        if not self._many_responses:
            return []
        return self._many_responses.pop(0)


class FakeConnection:
    """Соединение с БД, отдающее один и тот же тестовый курсор."""

    def __init__(self, cursor: FakeCursor) -> None:
        """Сохранить тестовый курсор.

        Args:
            cursor: Курсор, который должен возвращаться из `cursor()`.
        """
        self._cursor = cursor
        self.commits = 0

    def cursor(self, cursor_factory: object | None = None) -> FakeCursor:
        """Вернуть тестовый курсор.

        Args:
            cursor_factory: Неиспользуемая фабрика курсора.

        Returns:
            Подготовленный тестовый курсор.
        """
        return self._cursor

    def commit(self) -> None:
        """Зафиксировать транзакцию."""
        self.commits += 1


class FakePostgresRepository(PostgresRepository):
    """Тестовый репозиторий с подменённым соединением."""

    def __init__(self, connection: FakeConnection) -> None:
        """Создать репозиторий поверх фейкового соединения.

        Args:
            connection: Подготовленное тестовое соединение.
        """
        super().__init__(
            DatabaseConfig(
                host="localhost",
                port=5432,
                user="postgres",
                password=SecretStr("secret"),
                database="kubachi",
            )
        )
        self._fake_connection = connection

    @contextmanager
    def _connect(self) -> Iterator[FakeConnection]:
        """Вернуть фейковое соединение вместо реального.

        Yields:
            Подготовленное тестовое соединение.
        """
        yield self._fake_connection


def test_log_action_increments_search_counter_for_search_queries() -> None:
    """Поисковое действие должно увеличивать `users.searches_count`."""
    cursor = FakeCursor(responses=[{"id": 7}])
    connection = FakeConnection(cursor)
    repository = FakePostgresRepository(connection)

    repository.log_action("привет", 123456, action_type="search")

    assert connection.commits == 1
    assert any(
        "SET searches_count = searches_count + %s" in query for query, _ in cursor.executed
    )


def test_log_action_does_not_increment_search_counter_for_commands() -> None:
    """Команда не должна увеличивать счётчик поисков."""
    cursor = FakeCursor(responses=[{"id": 7}])
    connection = FakeConnection(cursor)
    repository = FakePostgresRepository(connection)

    repository.log_action("/me", 123456, action_type="command")

    assert connection.commits == 1
    assert not any(
        "SET searches_count = searches_count + %s" in query for query, _ in cursor.executed
    )


def test_insert_suggestion_increments_suggestion_counter() -> None:
    """Создание предложения должно увеличивать `users.suggestions_count`."""
    cursor = FakeCursor(responses=[{"id": 7}, {"id": 21}])
    connection = FakeConnection(cursor)
    repository = FakePostgresRepository(connection)
    author = TelegramUser(chat_id=123456, username="tester", first_name="Иван", last_name="")

    suggestion_id = repository.insert_suggestion(author, "Добавить новые примеры")

    assert suggestion_id == 21
    assert connection.commits == 1
    assert any(
        "SET suggestions_count = suggestions_count + 1" in query for query, _ in cursor.executed
    )


def test_create_broadcast_saves_snapshot_of_recipients() -> None:
    """Создание рассылки должно сохранять запись и адресатов со статусом pending."""
    cursor = FakeCursor(responses=[{"id": 5}, {"id": 77}])
    connection = FakeConnection(cursor)
    repository = FakePostgresRepository(connection)

    recipients = [
        BroadcastRecipient(
            user_id=10,
            user=TelegramUser(chat_id=111, username="one", first_name="Один", last_name=""),
        ),
        BroadcastRecipient(
            user_id=11,
            user=TelegramUser(chat_id=222, username="two", first_name="Два", last_name=""),
        ),
    ]

    broadcast_id = repository.create_broadcast(
        created_by_chat_id=123456,
        audience=BroadcastAudience.ALL,
        audience_days=None,
        source_chat_id=123456,
        source_message_ids=[99, 100],
        text_preview="Новость",
        content_type="текст",
        recipients=recipients,
    )

    assert broadcast_id == 77
    assert connection.commits == 1
    assert any("INSERT INTO broadcasts" in query for query, _ in cursor.executed)
    assert sum(
        1 for query, _ in cursor.executed if "INSERT INTO broadcast_source_messages" in query
    ) == 2
    assert sum(
        1 for query, params in cursor.executed if "INSERT INTO broadcast_deliveries" in query
    ) == 2
    assert all(
        params[-1] == BroadcastDeliveryStatus.PENDING.value
        for query, params in cursor.executed
        if "INSERT INTO broadcast_deliveries" in query
    )
