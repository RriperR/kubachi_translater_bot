"""Работа со словарными статьями в PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DatabaseConfig
from models import DictionaryEntry, DictionarySource, SearchMode, TelegramUser, UserSubmittedEntry
from normalization import compact_lines, normalize_query, split_values

_CANDIDATE_LIMIT = 250


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

    def search_entries(self, query: str, mode: SearchMode) -> list[DictionaryEntry]:
        """Вернуть кандидатов для поиска, отфильтрованных на стороне PostgreSQL.

        Args:
            query: Поисковый запрос пользователя.
            mode: Режим поиска, влияющий на SQL-предикаты.

        Returns:
            Список словарных статей-кандидатов для дальнейшего ранжирования в Python.
        """
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []

        query_sql, parameters = self._build_search_query(normalized_query, mode)
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(query_sql, parameters)
            rows = cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    def import_entries(self, entries: Iterable[DictionaryEntry]) -> int:
        """Импортировать словарные статьи в PostgreSQL.

        Args:
            entries: Последовательность нормализованных статей для загрузки.

        Returns:
            Число реально добавленных статей.
        """
        payload = [self._entry_to_row(entry) for entry in entries]
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
                            normalized_word,
                            normalized_translation,
                            normalized_comments,
                            normalized_search_text,
                            contributor_username,
                            contributor_first_name,
                            contributor_last_name,
                            banner
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        normalized_word,
                        normalized_translation,
                        normalized_comments,
                        normalized_search_text,
                        contributor_username,
                        contributor_first_name,
                        contributor_last_name,
                        banner
                    )
                    VALUES (%s, %s, %s, %s, %s, '', %s, %s, '', %s, %s, %s, %s, %s)
                    """,
                    (
                        self._source.value,
                        entry.word,
                        entry.translation,
                        list(compact_lines(split_values(entry.phrases_raw, "%"))),
                        list(compact_lines(split_values(entry.supporting_raw, "\\"))),
                        normalize_query(entry.word),
                        normalize_query(entry.translation),
                        self._build_search_text(
                            entry.word,
                            entry.translation,
                            compact_lines(split_values(entry.phrases_raw, "%")),
                            compact_lines(split_values(entry.supporting_raw, "\\")),
                            "",
                        ),
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
                        END,
                        normalized_comments = btrim(
                            regexp_replace(
                                lower(
                                    translate(
                                        CASE
                                            WHEN btrim(comments) = '' THEN %s
                                            ELSE comments || E'\n' || %s
                                        END,
                                        '1!l|I',
                                        'iiiii'
                                    )
                                ),
                                '\s+',
                                ' ',
                                'g'
                            )
                        ),
                        normalized_search_text = btrim(
                            regexp_replace(
                                lower(
                                    translate(
                                        concat_ws(
                                            ' ',
                                            word,
                                            translation,
                                            array_to_string(examples, ' '),
                                            array_to_string(notes, ' '),
                                            CASE
                                                WHEN btrim(comments) = '' THEN %s
                                                ELSE comments || E'\n' || %s
                                            END
                                        ),
                                        '1!l|I',
                                        'iiiii'
                                    )
                                ),
                                '\s+',
                                ' ',
                                'g'
                            )
                        )
                    WHERE source = %s
                      AND CONCAT(word, ' - ', translation) = %s
                    """,
                    (
                        comment_line,
                        comment_line,
                        comment_line,
                        comment_line,
                        comment_line,
                        comment_line,
                        self._source.value,
                        title,
                    ),
                )
                updated = int(cursor.rowcount) > 0
            connection.commit()
        return updated

    def _build_search_query(self, query: str, mode: SearchMode) -> tuple[str, tuple[object, ...]]:
        if mode == SearchMode.LITE:
            return (
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
                  AND (
                    regexp_split_to_array(
                        regexp_replace(normalized_word, '\s*,\s*', ',', 'g'),
                        ','
                    ) @> ARRAY[%s]::text[]
                    OR regexp_split_to_array(normalized_translation, '\s+') @> ARRAY[%s]::text[]
                    OR (
                        source = %s
                        AND regexp_split_to_array(normalized_comments, '\s+') @> ARRAY[%s]::text[]
                    )
                  )
                ORDER BY id
                LIMIT %s
                """,
                (
                    self._source.value,
                    query,
                    query,
                    DictionarySource.CORE.value,
                    query,
                    _CANDIDATE_LIMIT,
                ),
            )

        return (
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
              AND (
                to_tsvector('simple', normalized_search_text) @@ plainto_tsquery('simple', %s)
                OR normalized_word LIKE %s
                OR normalized_translation LIKE %s
              )
            ORDER BY id
            LIMIT %s
            """,
            (
                self._source.value,
                query,
                f"{query}%",
                f"{query}%",
                _CANDIDATE_LIMIT,
            ),
        )

    def _entry_to_row(self, entry: DictionaryEntry) -> tuple[object, ...]:
        return (
            self._source.value,
            entry.word,
            entry.translation,
            list(entry.examples),
            list(entry.notes),
            entry.comments,
            normalize_query(entry.word),
            normalize_query(entry.translation),
            normalize_query(entry.comments),
            self._build_search_text(
                entry.word,
                entry.translation,
                entry.examples,
                entry.notes,
                entry.comments,
            ),
            entry.contributor_username,
            entry.contributor_first_name,
            entry.contributor_last_name,
            entry.banner,
        )

    @staticmethod
    def _build_search_text(
        word: str,
        translation: str,
        examples: Iterable[str],
        notes: Iterable[str],
        comments: str,
    ) -> str:
        parts = [word, translation, *examples, *notes, comments]
        return normalize_query(" ".join(part for part in parts if part))

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
