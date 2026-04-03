"""Админские операции для PostgreSQL-репозитория словаря."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import RealDictCursor

from models import AdminCommentRecord, AdminUserEntryRecord, DictionarySource, TelegramUser
from normalization import compact_lines, normalize_query, split_values

from .dictionary_rag_repository import DictionaryRagRepositoryMixin
from .dictionary_repository import DictionaryRepositoryMixin
from .dictionary_search_repository import DictionarySearchRepositoryMixin


class DictionaryAdminRepositoryMixin(
    DictionaryRepositoryMixin,
    DictionarySearchRepositoryMixin,
    DictionaryRagRepositoryMixin,
):
    """Поведение PostgreSQL-репозитория для админского просмотра и управления."""

    def list_user_entries(
        self,
        limit: int,
        offset: int = 0,
        word_filter: str | None = None,
        author_filter: str | None = None,
    ) -> list[AdminUserEntryRecord]:
        """Получить список пользовательских статей для админки.

        Args:
            limit: Максимальное число записей.
            offset: Смещение для пагинации.
            word_filter: Необязательный фильтр по слову статьи.
            author_filter: Необязательный фильтр по автору статьи.

        Returns:
            Список пользовательских статей с метаданными автора.

        Raises:
            ValueError: Если метод вызван не на USER-репозитории.
        """
        if self._source != DictionarySource.USER:
            raise ValueError("Список пользовательских статей доступен только для USER-репозитория")
        rows = self._fetch_admin_entry_rows(
            limit=limit,
            offset=offset,
            word_filter=word_filter,
            author_filter=author_filter,
        )
        return [self._row_to_admin_user_entry(row) for row in rows]

    def get_user_entry(self, entry_id: int) -> AdminUserEntryRecord | None:
        """Получить одну пользовательскую статью для подробного просмотра.

        Args:
            entry_id: Идентификатор статьи.

        Returns:
            Пользовательская статья или `None`, если запись не найдена.

        Raises:
            ValueError: Если метод вызван не на USER-репозитории.
        """
        if self._source != DictionarySource.USER:
            raise ValueError(
                "Просмотр пользовательской статьи доступен только для USER-репозитория"
            )
        rows = self._fetch_admin_entry_rows(entry_id=entry_id, limit=1, offset=0)
        if not rows:
            return None
        return self._row_to_admin_user_entry(rows[0])

    def update_user_entry_field(self, entry_id: int, field_name: str, raw_value: str) -> bool:
        """Обновить одно поле пользовательской статьи из админки.

        Args:
            entry_id: Идентификатор статьи.
            field_name: Имя редактируемого поля.
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
            elif field_name in {"phrases_raw", "phrases"}:
                self._replace_examples(cursor, entry_id, compact_lines(split_values(value, "%")))
                cursor.execute(
                    "UPDATE dictionary_entries SET updated_at = NOW() WHERE id = %s",
                    (entry_id,),
                )
            elif field_name in {"supporting_raw", "supporting"}:
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
        """Удалить пользовательскую статью из базы.

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
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM dictionary_entries WHERE id = %s AND source = %s",
                    (entry_id, self._source.value),
                )
                deleted = bool(cursor.rowcount > 0)
            connection.commit()
        return deleted

    def list_comments(
        self,
        limit: int,
        offset: int = 0,
        entry_filter: str | None = None,
        author_filter: str | None = None,
    ) -> list[AdminCommentRecord]:
        """Получить список комментариев для админки.

        Args:
            limit: Максимальное число записей.
            offset: Смещение для пагинации.
            entry_filter: Необязательный фильтр по статье.
            author_filter: Необязательный фильтр по автору комментария.

        Returns:
            Список комментариев с авторами.
        """
        conditions = ["1 = 1"]
        params: list[object] = []

        if entry_filter:
            normalized_filter = normalize_query(entry_filter)
            if normalized_filter:
                conditions.append(
                    """
                    (
                        entries.normalized_word LIKE %s
                        OR entries.normalized_translation LIKE %s
                        OR comments.normalized_text LIKE %s
                        OR entries.id::text = %s
                    )
                    """
                )
                like_filter = f"%{normalized_filter}%"
                params.extend([like_filter, like_filter, like_filter, entry_filter.strip()])

        if author_filter:
            normalized_author_text = normalize_query(author_filter)
            if normalized_author_text:
                normalized_author = f"%{normalized_author_text}%"
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
                "SELECT entry_id FROM dictionary_entry_comments WHERE id = %s",
                (comment_id,),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return False

            entry_id = int(row["entry_id"])
            cursor.execute("DELETE FROM dictionary_entry_comments WHERE id = %s", (comment_id,))
            cursor.execute(
                "UPDATE dictionary_entries SET updated_at = NOW() WHERE id = %s",
                (entry_id,),
            )
            self._sync_rag_chunks_for_entry(cursor, entry_id)
            connection.commit()
        return True

    def _fetch_admin_entry_rows(
        self,
        limit: int,
        offset: int,
        word_filter: str | None = None,
        author_filter: str | None = None,
        entry_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Получить строки пользовательских статей из PostgreSQL.

        Args:
            limit: Максимальное число строк.
            offset: Смещение для пагинации.
            word_filter: Необязательный фильтр по слову статьи.
            author_filter: Необязательный фильтр по автору статьи.
            entry_id: Необязательный точный фильтр по идентификатору статьи.

        Returns:
            Список словарей PostgreSQL с агрегированными полями статьи.
        """
        conditions = ["e.source = %s"]
        params: list[object] = [self._source.value]

        if entry_id is not None:
            conditions.append("e.id = %s")
            params.append(entry_id)

        if word_filter:
            normalized_word_text = normalize_query(word_filter)
            if normalized_word_text:
                normalized_word = f"%{normalized_word_text}%"
                conditions.append(
                    """
                    (
                        e.normalized_word LIKE %s
                        OR e.normalized_translation LIKE %s
                        OR e.word ILIKE %s
                        OR e.translation ILIKE %s
                    )
                    """
                )
                params.extend(
                    [
                        normalized_word,
                        normalized_word,
                        f"%{word_filter.strip()}%",
                        f"%{word_filter.strip()}%",
                    ]
                )

        if author_filter:
            normalized_author_text = normalize_query(author_filter)
            if normalized_author_text:
                normalized_author = f"%{normalized_author_text}%"
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
            WITH examples_agg AS (
                SELECT
                    entry_id,
                    array_agg(text ORDER BY position) AS examples,
                    string_agg(normalized_text, ' ' ORDER BY position) AS normalized_examples
                FROM dictionary_entry_examples
                GROUP BY entry_id
            ),
            notes_agg AS (
                SELECT
                    entry_id,
                    array_agg(text ORDER BY position) AS notes,
                    string_agg(normalized_text, ' ' ORDER BY position) AS normalized_notes
                FROM dictionary_entry_notes
                GROUP BY entry_id
            ),
            comments_agg AS (
                SELECT
                    entry_id,
                    string_agg(text, E'\\n' ORDER BY id) AS comments,
                    string_agg(normalized_text, ' ' ORDER BY id) AS normalized_comments
                FROM dictionary_entry_comments
                GROUP BY entry_id
            )
            SELECT
                e.id,
                e.source,
                e.word,
                e.translation,
                e.created_at,
                e.updated_at,
                COALESCE(examples_agg.examples, ARRAY[]::text[]) AS examples,
                COALESCE(notes_agg.notes, ARRAY[]::text[]) AS notes,
                COALESCE(comments_agg.comments, '') AS comments,
                COALESCE(examples_agg.normalized_examples, '') AS normalized_examples,
                COALESCE(notes_agg.normalized_notes, '') AS normalized_notes,
                COALESCE(comments_agg.normalized_comments, '') AS normalized_comments,
                users.chatid AS contributor_chat_id,
                users.username AS contributor_username,
                users.firstname AS contributor_first_name,
                users.lastname AS contributor_last_name
            FROM dictionary_entries AS e
            LEFT JOIN examples_agg ON examples_agg.entry_id = e.id
            LEFT JOIN notes_agg ON notes_agg.entry_id = e.id
            LEFT JOIN comments_agg ON comments_agg.entry_id = e.id
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
        return [dict(row) for row in rows]

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
