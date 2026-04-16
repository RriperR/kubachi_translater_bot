"""Операции изменения и загрузки словарных статей в PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from psycopg2.extras import RealDictCursor

from models import (
    AdminCommentRecord,
    AdminUserEntryRecord,
    DictionaryEntry,
    DictionarySource,
    SearchMode,
    TelegramUser,
    UserSubmittedEntry,
)
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
            author_id = self._find_existing_user_id(
                cursor,
                chat_id=entry.contributor.chat_id,
                username=entry.contributor.username,
                first_name=entry.contributor.first_name,
                last_name=entry.contributor.last_name,
            )
            self._adjust_user_counter(cursor, author_id, "user_entries_count", 1)
            self._sync_rag_chunks_for_entry(cursor, inserted_id)
            connection.commit()

    def list_user_entries(
        self,
        limit: int,
        offset: int = 0,
        word_filter: str | None = None,
        author_filter: str | None = None,
    ) -> list[AdminUserEntryRecord]:
        """Получить список пользовательских статей для админки.

        Args:
            limit: Максимальный размер страницы.
            offset: Смещение для пагинации.
            word_filter: Необязательный фильтр по слову статьи.
            author_filter: Необязательный фильтр по имени, username или chat_id автора.

        Returns:
            Страница пользовательских статей с данными автора.

        Raises:
            ValueError: Если метод вызван не на USER-репозитории.
        """
        if self._source != DictionarySource.USER:
            raise ValueError("Список пользовательских статей доступен только для USER-репозитория")

        conditions = ["e.source = %s"]
        params: list[object] = [self._source.value]
        if word_filter:
            conditions.append("e.normalized_word LIKE %s")
            params.append(f"%{normalize_query(word_filter)}%")
        if author_filter:
            conditions.append(
                """
                (
                    lower(COALESCE(users.username, '')) LIKE %s
                    OR lower(COALESCE(users.firstname, '')) LIKE %s
                    OR lower(COALESCE(users.lastname, '')) LIKE %s
                    OR COALESCE(users.chatid, '') LIKE %s
                )
                """
            )
            normalized_filter = f"%{normalize_query(author_filter)}%"
            params.extend(
                [
                    normalized_filter,
                    normalized_filter,
                    normalized_filter,
                    normalized_filter,
                ]
            )

        query = """
            SELECT
                e.id,
                e.source,
                e.word,
                e.translation,
                e.created_at,
                users.chatid AS contributor_chat_id,
                users.username AS contributor_username,
                users.firstname AS contributor_first_name,
                users.lastname AS contributor_last_name
            FROM dictionary_entries AS e
            LEFT JOIN users ON users.id = e.user_id
            WHERE __CONDITIONS__
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT %s OFFSET %s
        """.replace("__CONDITIONS__", " AND ".join(conditions))  # noqa: S608
        params.extend([limit, offset])
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
        return [self._row_to_admin_user_entry(dict(row)) for row in rows]

    def get_user_entry(self, entry_id: int) -> AdminUserEntryRecord | None:
        """Получить одну пользовательскую статью для подробного просмотра в админке.

        Args:
            entry_id: Идентификатор статьи.

        Returns:
            Пользовательская статья с автором или `None`, если запись не найдена.
        """
        row = self._fetch_entry_rows("by_id", (entry_id,))
        if not row:
            return None
        admin_row = row[0]
        if str(admin_row["source"]).strip() != DictionarySource.USER.value:
            return None

        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                """
                SELECT
                    e.created_at,
                    users.chatid AS contributor_chat_id
                FROM dictionary_entries AS e
                LEFT JOIN users ON users.id = e.user_id
                WHERE e.id = %s
                """,
                (entry_id,),
            )
            meta_row = cursor.fetchone()
        if meta_row is not None:
            admin_row["created_at"] = meta_row["created_at"]
            admin_row["contributor_chat_id"] = meta_row["contributor_chat_id"]
        return self._row_to_admin_user_entry(admin_row)

    def update_user_entry_field(self, entry_id: int, field_name: str, raw_value: str) -> bool:
        """Обновить одно поле пользовательской статьи из админки.

        Args:
            entry_id: Идентификатор статьи.
            field_name: Поле для редактирования: `word`, `translation`, `phrases`, `supporting`.
            raw_value: Новое значение поля в текстовом виде.

        Returns:
            `True`, если статья найдена и обновлена.

        Raises:
            ValueError: Если метод вызван не на USER-репозитории или поле неизвестно.
        """
        if self._source != DictionarySource.USER:
            raise ValueError("Редактирование доступно только для USER-репозитория")

        value = raw_value.strip()
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT id FROM dictionary_entries WHERE id = %s AND source = %s",
                (entry_id, self._source.value),
            )
            if cursor.fetchone() is None:
                connection.commit()
                return False

            if field_name == "word":
                cursor.execute(
                    """
                    UPDATE dictionary_entries
                    SET word = %s,
                        normalized_word = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (value, normalize_query(value), entry_id),
                )
            elif field_name == "translation":
                cursor.execute(
                    """
                    UPDATE dictionary_entries
                    SET translation = %s,
                        normalized_translation = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (value, self._normalize_token_text(value), entry_id),
                )
            elif field_name == "phrases":
                self._replace_examples(cursor, entry_id, compact_lines(split_values(value, "%")))
                cursor.execute(
                    "UPDATE dictionary_entries SET updated_at = NOW() WHERE id = %s",
                    (entry_id,),
                )
            elif field_name == "supporting":
                self._replace_notes(cursor, entry_id, compact_lines(split_values(value, "\\")))
                cursor.execute(
                    "UPDATE dictionary_entries SET updated_at = NOW() WHERE id = %s",
                    (entry_id,),
                )
            else:
                raise ValueError(f"Неизвестное поле для редактирования: {field_name}")

            self._sync_rag_chunks_for_entry(cursor, entry_id)
            connection.commit()
        return True

    def delete_user_entry(self, entry_id: int) -> bool:
        """Удалить пользовательскую статью по идентификатору.

        Args:
            entry_id: Идентификатор статьи.

        Returns:
            `True`, если статья была удалена.

        Raises:
            ValueError: Если метод вызван не на USER-репозитории.
        """
        if self._source != DictionarySource.USER:
            raise ValueError("Удаление доступно только для USER-репозитория")
        with self._connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT user_id
                    FROM dictionary_entries
                    WHERE id = %s
                      AND source = %s
                    """,
                    (entry_id, self._source.value),
                )
                row = cursor.fetchone()
                if row is None:
                    connection.commit()
                    return False

                user_id = int(row["user_id"]) if row["user_id"] is not None else None
                self._decrement_comment_counters_for_entry(cursor, entry_id)
                cursor.execute(
                    "DELETE FROM dictionary_entries WHERE id = %s AND source = %s",
                    (entry_id, self._source.value),
                )
                deleted = bool(cursor.rowcount > 0)
                if deleted:
                    self._adjust_user_counter(cursor, user_id, "user_entries_count", -1)
            connection.commit()
        return deleted

    def list_comments(
        self,
        limit: int,
        offset: int = 0,
        entry_filter: str | None = None,
        author_filter: str | None = None,
    ) -> list[AdminCommentRecord]:
        """Получить список комментариев для админки с фильтрами.

        Args:
            limit: Максимальный размер страницы.
            offset: Смещение для пагинации.
            entry_filter: Необязательный фильтр по статье.
            author_filter: Необязательный фильтр по автору комментария.

        Returns:
            Страница комментариев для admin panel.
        """
        conditions = ["1 = 1"]
        params: list[object] = []
        if entry_filter:
            normalized_filter = f"%{normalize_query(entry_filter)}%"
            conditions.append(
                """
                (
                    lower(concat(entries.word, ' - ', entries.translation)) LIKE %s
                    OR entries.normalized_word LIKE %s
                    OR entries.normalized_translation LIKE %s
                )
                """
            )
            params.extend([normalized_filter, normalized_filter, normalized_filter])
        if author_filter:
            normalized_author = f"%{normalize_query(author_filter)}%"
            conditions.append(
                """
                (
                    lower(COALESCE(users.username, '')) LIKE %s
                    OR lower(COALESCE(users.firstname, '')) LIKE %s
                    OR lower(COALESCE(users.lastname, '')) LIKE %s
                    OR COALESCE(users.chatid, '') LIKE %s
                )
                """
            )
            params.extend(
                [
                    normalized_author,
                    normalized_author,
                    normalized_author,
                    normalized_author,
                ]
            )

        query = """
            SELECT
                comments.id,
                comments.entry_id,
                comments.text,
                comments.created_at,
                entries.word,
                entries.translation,
                users.chatid AS contributor_chat_id,
                users.username AS contributor_username,
                users.firstname AS contributor_first_name,
                users.lastname AS contributor_last_name
            FROM dictionary_entry_comments AS comments
            JOIN dictionary_entries AS entries ON entries.id = comments.entry_id
            LEFT JOIN users ON users.id = comments.user_id
            WHERE __CONDITIONS__
            ORDER BY comments.created_at DESC, comments.id DESC
            LIMIT %s OFFSET %s
        """.replace("__CONDITIONS__", " AND ".join(conditions))  # noqa: S608
        params.extend([limit, offset])
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
        return [self._row_to_admin_comment(dict(row)) for row in rows]

    def delete_comment(self, comment_id: int) -> bool:
        """Удалить комментарий и пересинхронизировать RAG-чанки статьи.

        Args:
            comment_id: Идентификатор комментария.

        Returns:
            `True`, если комментарий существовал и был удален.
        """
        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT entry_id, user_id FROM dictionary_entry_comments WHERE id = %s",
                (comment_id,),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return False
            entry_id = int(row["entry_id"])
            user_id = int(row["user_id"]) if row["user_id"] is not None else None
            cursor.execute("DELETE FROM dictionary_entry_comments WHERE id = %s", (comment_id,))
            self._adjust_user_counter(cursor, user_id, "comments_count", -1)
            self._sync_rag_chunks_for_entry(cursor, entry_id)
            connection.commit()
        return True

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
                SELECT id, user_id
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
            user_id = self._ensure_user_record(cursor, author)
            cursor.execute(
                """
                INSERT INTO dictionary_entry_comments (
                    entry_id,
                    user_id,
                    text,
                    normalized_text
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    entry_id,
                    user_id,
                    comment_line,
                    self._normalize_token_text(comment_line),
                ),
            )
            cursor.execute(
                "UPDATE dictionary_entries SET updated_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            self._adjust_user_counter(cursor, user_id, "comments_count", 1)
            self._sync_rag_chunks_for_entry(cursor, entry_id)
            connection.commit()
        return True

    def _find_existing_user_id(
        self,
        cursor: Any,
        chat_id: int | None,
        username: str | None,
        first_name: str,
        last_name: str,
    ) -> int | None:
        if chat_id is not None:
            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE chatid = %s
                """,
                (str(chat_id),),
            )
            row = cursor.fetchone()
            if row is not None:
                return int(row["id"])

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE username IS NOT DISTINCT FROM %s
              AND firstname = %s
              AND lastname = %s
            LIMIT 1
            """,
            (username, first_name, last_name),
        )
        row = cursor.fetchone()
        if row is not None:
            return int(row["id"])
        return None

    def _ensure_user_record(self, cursor: Any, user: TelegramUser) -> int:
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
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (chatid) DO UPDATE
            SET username = EXCLUDED.username,
                firstname = EXCLUDED.firstname,
                lastname = EXCLUDED.lastname,
                updated_at = NOW()
            RETURNING id
            """,
            (
                user.username,
                user.first_name,
                user.last_name,
                str(user.chat_id),
                SearchMode.LITE.value,
            ),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            raise RuntimeError("Не удалось создать или обновить автора словарной статьи")
        return int(inserted["id"])

    def _insert_entry(
        self,
        cursor: Any,
        entry: DictionaryEntry,
        chat_id: int | None = None,
    ) -> int | None:
        user_id = self._resolve_entry_user_id(cursor, entry, chat_id)
        cursor.execute(
            """
            INSERT INTO dictionary_entries (
                source,
                word,
                translation,
                normalized_word,
                normalized_translation,
                user_id
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
                user_id,
            ),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            return None
        return int(inserted["id"])

    def _resolve_entry_user_id(
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

        return self._find_existing_user_id(
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
                    user_id,
                    text,
                    normalized_text
                )
            VALUES (%s, NULL, %s, %s)
            """,
            [(entry_id, line, self._normalize_token_text(line)) for line in comment_lines],
        )

    @staticmethod
    def _row_to_optional_author(row: dict[str, Any]) -> TelegramUser | None:
        chat_id = row.get("contributor_chat_id")
        username = row.get("contributor_username")
        first_name = str(row.get("contributor_first_name") or "")
        last_name = str(row.get("contributor_last_name") or "")
        if chat_id is None and username is None and not first_name and not last_name:
            return None
        return TelegramUser(
            chat_id=int(chat_id or 0),
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

    def _row_to_admin_user_entry(self, row: dict[str, Any]) -> AdminUserEntryRecord:
        return AdminUserEntryRecord(
            entry_id=int(row["id"]),
            entry=self._row_to_entry(row),
            created_at=row["created_at"],
            author=self._row_to_optional_author(row),
        )

    def _row_to_admin_comment(self, row: dict[str, Any]) -> AdminCommentRecord:
        return AdminCommentRecord(
            comment_id=int(row["id"]),
            entry_id=int(row["entry_id"]),
            entry_title=f"{str(row['word']).strip()} - {str(row['translation']).strip()}",
            comment_text=str(row["text"]).strip(),
            created_at=row["created_at"],
            author=self._row_to_optional_author(row),
        )
