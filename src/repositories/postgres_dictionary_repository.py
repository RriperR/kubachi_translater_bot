"""Работа со словарными статьями в PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DatabaseConfig
from models import DictionaryEntry, DictionarySource, TelegramUser, UserSubmittedEntry
from normalization import compact_lines, split_values


class PostgresDictionaryRepository:
    """Репозиторий словарных статей в PostgreSQL."""

    def __init__(self, config: DatabaseConfig, source: DictionarySource) -> None:
        """Сохранить настройки БД и источник словарных статей.

        Args:
            config: Настройки подключения к PostgreSQL.
            source: Источник статей, закрепленный за репозиторием.
        """
        self._config = config
        self._source = source

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

    def has_entries(self) -> bool:
        """Проверить, импортированы ли статьи этого источника.

        Returns:
            `True`, если в таблице уже есть хотя бы одна статья данного источника.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT 1 FROM dictionary_entries WHERE source = %s LIMIT 1",
                (self._source.value,),
            )
            return cursor.fetchone() is not None

    def import_entries(self, entries: Iterable[DictionaryEntry]) -> int:
        """Импортировать словарные статьи в PostgreSQL.

        Args:
            entries: Последовательность нормализованных статей для загрузки.

        Returns:
            Число реально добавленных статей.
        """
        payload = [
            (
                self._source.value,
                entry.word,
                entry.translation,
                list(entry.examples),
                list(entry.notes),
                entry.comments,
                entry.contributor_username,
                entry.contributor_first_name,
                entry.contributor_last_name,
                entry.banner,
            )
            for entry in entries
        ]
        if not payload:
            return 0

        inserted = 0
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for row in payload:
                    cursor.execute(
                        """
                        INSERT INTO dictionary_entries (
                            source,
                            word,
                            translation,
                            examples,
                            notes,
                            comments,
                            contributor_username,
                            contributor_first_name,
                            contributor_last_name,
                            banner
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source, word, translation) DO NOTHING
                        """,
                        row,
                    )
                    inserted += cursor.rowcount
            connection.commit()
        return inserted

    def list_entries(self) -> list[DictionaryEntry]:
        """Прочитать все статьи текущего источника из PostgreSQL.

        Returns:
            Список словарных статей этого источника.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    word,
                    translation,
                    examples,
                    notes,
                    comments,
                    contributor_username,
                    contributor_first_name,
                    contributor_last_name,
                    banner
                FROM dictionary_entries
                WHERE source = %s
                ORDER BY id
                """,
                (self._source.value,),
            )
            rows = cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    def append_user_entry(self, entry: UserSubmittedEntry) -> None:
        """Добавить пользовательскую статью в PostgreSQL.

        Args:
            entry: Пользовательская статья, которую нужно сохранить.

        Raises:
            ValueError: Если метод вызван не для пользовательского репозитория.
        """
        if self._source != DictionarySource.USER:
            raise ValueError(
                "Добавление пользовательских статей доступно только для USER-репозитория"
            )

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO dictionary_entries (
                        source,
                        word,
                        translation,
                        examples,
                        notes,
                        comments,
                        contributor_username,
                        contributor_first_name,
                        contributor_last_name,
                        banner
                    )
                    VALUES (%s, %s, %s, %s, %s, '', %s, %s, %s, %s)
                    """,
                    (
                        self._source.value,
                        entry.word,
                        entry.translation,
                        list(compact_lines(split_values(entry.phrases_raw, "%"))),
                        list(compact_lines(split_values(entry.supporting_raw, "\\"))),
                        entry.contributor.username,
                        entry.contributor.first_name,
                        entry.contributor.last_name,
                        "!!!ПОЛЬЗОВАТЕЛЬСКИЙ ПЕРЕВОД!!!",
                    ),
                )
            connection.commit()

    def append_comment(self, title: str, comment: str, author: TelegramUser) -> bool:
        """Добавить комментарий к существующей статье.

        Args:
            title: Заголовок статьи в формате `слово - перевод`.
            comment: Текст комментария пользователя.
            author: Автор комментария.

        Returns:
            `True`, если статья найдена и обновлена, иначе `False`.
        """
        comment_line = f"Пользователь оставил комментарий: {comment}"
        if author.username:
            comment_line += f" (@{author.username})"
        elif author.first_name:
            comment_line += f" ({author.first_name})"

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE dictionary_entries
                    SET comments = CASE
                        WHEN btrim(comments) = '' THEN %s
                        ELSE comments || E'\n' || %s
                    END
                    WHERE source = %s
                      AND CONCAT(word, ' - ', translation) = %s
                    """,
                    (comment_line, comment_line, self._source.value, title),
                )
                updated = int(cursor.rowcount) > 0
            connection.commit()
        return updated

    def _row_to_entry(self, row: dict[str, Any]) -> DictionaryEntry:
        return DictionaryEntry(
            source=self._source,
            word=str(row["word"]).strip(),
            translation=str(row["translation"]).strip(),
            examples=tuple(row.get("examples") or ()),
            notes=tuple(row.get("notes") or ()),
            comments=str(row.get("comments") or "").strip(),
            contributor_username=row.get("contributor_username"),
            contributor_first_name=row.get("contributor_first_name"),
            contributor_last_name=row.get("contributor_last_name"),
            banner=row.get("banner"),
        )
