"""Операции изменения и загрузки словарных статей в PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from psycopg2.extras import RealDictCursor

from models import DictionaryEntry, DictionarySource, TelegramUser, UserSubmittedEntry
from normalization import compact_lines, normalize_query, split_values

from .base import PostgresRepositoryBase


class DictionaryRepositoryMixin(PostgresRepositoryBase):
    """Поведение PostgreSQL-репозитория для импорта и записи статей."""

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
        payload = list(entries)
        if not payload:
            return 0

        inserted = 0
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                for entry in payload:
                    entry_id = self._insert_entry(cursor, entry)
                    if entry_id is None:
                        continue
                    inserted += 1
                    self._replace_examples(cursor, entry_id, entry.examples)
                    self._replace_notes(cursor, entry_id, entry.notes)
                    self._replace_comments(cursor, entry_id, entry.comments)
            connection.commit()

        self.sync_rag_chunks()
        return inserted

    def list_entries(self) -> list[DictionaryEntry]:
        """Прочитать все статьи текущего источника из PostgreSQL.

        Returns:
            Список словарных статей этого источника.
        """
        rows = self._fetch_entry_rows("by_source", (self._source.value,))
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

        examples = compact_lines(split_values(entry.phrases_raw, "%"))
        notes = compact_lines(split_values(entry.supporting_raw, "\\"))
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            inserted_id = self._insert_entry(
                cursor,
                DictionaryEntry(
                    source=self._source,
                    word=entry.word,
                    translation=entry.translation,
                    examples=examples,
                    notes=notes,
                    contributor_username=entry.contributor.username,
                    contributor_first_name=entry.contributor.first_name,
                    contributor_last_name=entry.contributor.last_name,
                ),
                chat_id=entry.contributor.chat_id,
            )
            if inserted_id is None:
                connection.commit()
                return

            self._replace_examples(cursor, inserted_id, examples)
            self._replace_notes(cursor, inserted_id, notes)
            self._sync_rag_chunks_for_entry(cursor, inserted_id)
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

        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT id
                FROM dictionary_entries
                WHERE source = %s
                  AND CONCAT(word, ' - ', translation) = %s
                """,
                (self._source.value, title),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return False

            entry_id = int(row["id"])
            contributor_id = self._ensure_contributor(cursor, author)
            cursor.execute(
                """
                INSERT INTO dictionary_entry_comments (
                    entry_id,
                    contributor_id,
                    text,
                    normalized_text
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    entry_id,
                    contributor_id,
                    comment_line,
                    self._normalize_token_text(comment_line),
                ),
            )
            self._sync_rag_chunks_for_entry(cursor, entry_id)
            connection.commit()
        return True

    def _ensure_contributor(self, cursor: Any, contributor: TelegramUser) -> int:
        return self._find_or_create_contributor(
            cursor,
            chat_id=contributor.chat_id,
            username=contributor.username,
            first_name=contributor.first_name,
            last_name=contributor.last_name,
        )

    def _find_or_create_contributor(
        self,
        cursor: Any,
        chat_id: int | None,
        username: str | None,
        first_name: str,
        last_name: str,
    ) -> int:
        if chat_id is not None:
            cursor.execute(
                """
                SELECT id
                FROM dictionary_contributors
                WHERE chat_id = %s
                """,
                (chat_id,),
            )
            row = cursor.fetchone()
            if row is not None:
                contributor_id = int(row["id"])
                cursor.execute(
                    """
                    UPDATE dictionary_contributors
                    SET username = %s,
                        first_name = %s,
                        last_name = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (username, first_name, last_name, contributor_id),
                )
                return contributor_id

        cursor.execute(
            """
            SELECT id
            FROM dictionary_contributors
            WHERE chat_id IS NULL
              AND username IS NOT DISTINCT FROM %s
              AND first_name = %s
              AND last_name = %s
            LIMIT 1
            """,
            (username, first_name, last_name),
        )
        row = cursor.fetchone()
        if row is not None:
            return int(row["id"])

        cursor.execute(
            """
            INSERT INTO dictionary_contributors (
                chat_id,
                username,
                first_name,
                last_name
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (chat_id, username, first_name, last_name),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            raise RuntimeError("Не удалось создать автора словарной статьи")
        return int(inserted["id"])

    def _insert_entry(
        self,
        cursor: Any,
        entry: DictionaryEntry,
        chat_id: int | None = None,
    ) -> int | None:
        contributor_id = self._resolve_entry_contributor_id(cursor, entry, chat_id)
        cursor.execute(
            """
            INSERT INTO dictionary_entries (
                source,
                word,
                translation,
                normalized_word,
                normalized_translation,
                contributor_id
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, word, translation) DO NOTHING
            RETURNING id
            """,
            (
                self._source.value,
                entry.word,
                entry.translation,
                normalize_query(entry.word),
                self._normalize_token_text(entry.translation),
                contributor_id,
            ),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            return None
        return int(inserted["id"])

    def _resolve_entry_contributor_id(
        self,
        cursor: Any,
        entry: DictionaryEntry,
        chat_id: int | None,
    ) -> int | None:
        username = self._strip_text(entry.contributor_username)
        first_name = self._strip_text(entry.contributor_first_name) or ""
        last_name = self._strip_text(entry.contributor_last_name) or ""
        if chat_id is None and username is None and first_name == "" and last_name == "":
            return None

        return self._find_or_create_contributor(
            cursor,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

    def _replace_examples(self, cursor: Any, entry_id: int, examples: tuple[str, ...]) -> None:
        cursor.execute("DELETE FROM dictionary_entry_examples WHERE entry_id = %s", (entry_id,))
        if not examples:
            return

        cursor.executemany(
            """
            INSERT INTO dictionary_entry_examples (
                entry_id,
                position,
                text,
                normalized_text
            )
            VALUES (%s, %s, %s, %s)
            """,
            [
                (entry_id, index, example, self._normalize_token_text(example))
                for index, example in enumerate(examples)
            ],
        )

    def _replace_notes(self, cursor: Any, entry_id: int, notes: tuple[str, ...]) -> None:
        cursor.execute("DELETE FROM dictionary_entry_notes WHERE entry_id = %s", (entry_id,))
        if not notes:
            return

        cursor.executemany(
            """
            INSERT INTO dictionary_entry_notes (
                entry_id,
                position,
                text,
                normalized_text
            )
            VALUES (%s, %s, %s, %s)
            """,
            [
                (entry_id, index, note, self._normalize_token_text(note))
                for index, note in enumerate(notes)
            ],
        )

    def _replace_comments(self, cursor: Any, entry_id: int, comments: str) -> None:
        cursor.execute("DELETE FROM dictionary_entry_comments WHERE entry_id = %s", (entry_id,))
        comment_lines = compact_lines(comments.splitlines())
        if not comment_lines:
            return

        cursor.executemany(
            """
            INSERT INTO dictionary_entry_comments (
                entry_id,
                contributor_id,
                text,
                normalized_text
            )
            VALUES (%s, NULL, %s, %s)
            """,
            [(entry_id, line, self._normalize_token_text(line)) for line in comment_lines],
        )
