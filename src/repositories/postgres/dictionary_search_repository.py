"""Поиск словарных статей в PostgreSQL."""

from __future__ import annotations

from typing import Any

from psycopg2.extras import RealDictCursor

from models import DictionaryEntry, DictionarySource, SearchMode
from normalization import meaningful_tokens, normalize_query

from .base import PostgresRepositoryBase

_CANDIDATE_LIMIT = 250
_USER_ENTRY_BANNER = "!!!ПОЛЬЗОВАТЕЛЬСКИЙ ПЕРЕВОД!!!"


class DictionarySearchRepositoryMixin(PostgresRepositoryBase):
    """Поведение PostgreSQL-репозитория для поиска словарных статей."""

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

        query_name, parameters = self._build_search_filter(normalized_query, mode)
        rows = self._fetch_entry_rows(query_name, parameters, limit=_CANDIDATE_LIMIT)
        return [self._row_to_entry(row) for row in rows]

    def _fetch_entry_rows(
        self,
        query_name: str,
        parameters: tuple[object, ...],
        limit: int | None = None,
        cursor: Any | None = None,
    ) -> list[dict[str, Any]]:
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
                e.contributor_id,
                contributors.username AS contributor_username,
                contributors.first_name AS contributor_first_name,
                contributors.last_name AS contributor_last_name
            FROM dictionary_entries AS e
            LEFT JOIN examples_agg ON examples_agg.entry_id = e.id
            LEFT JOIN notes_agg ON notes_agg.entry_id = e.id
            LEFT JOIN comments_agg ON comments_agg.entry_id = e.id
            LEFT JOIN dictionary_contributors AS contributors
                ON contributors.id = e.contributor_id
        """
        query_filters = {
            "by_source": "WHERE e.source = %s",
            "by_id": "WHERE e.id = %s",
            "search_lite": r"""
                WHERE e.source = %s
                  AND (
                    regexp_split_to_array(
                        regexp_replace(e.normalized_word, '\s*,\s*', ',', 'g'),
                        ','
                    ) @> ARRAY[%s]::text[]
                    OR regexp_split_to_array(e.normalized_translation, '\s+') @> ARRAY[%s]::text[]
                    OR (
                        e.source = %s
                        AND regexp_split_to_array(
                            COALESCE(comments_agg.normalized_comments, ''),
                            '\s+'
                        ) @> ARRAY[%s]::text[]
                    )
                  )
            """,
            "search_complex": r"""
                WHERE e.source = %s
                  AND (
                    to_tsvector(
                        'simple',
                        concat_ws(
                            ' ',
                            e.normalized_word,
                            e.normalized_translation,
                            COALESCE(examples_agg.normalized_examples, ''),
                            COALESCE(notes_agg.normalized_notes, ''),
                            COALESCE(comments_agg.normalized_comments, '')
                        )
                    ) @@ plainto_tsquery('simple', %s)
                    OR e.normalized_word LIKE %s
                    OR e.normalized_translation LIKE %s
                  )
            """,
        }
        query += "\n" + query_filters[query_name] + "\nORDER BY e.id"
        params = parameters
        if limit is not None:
            query += "\nLIMIT %s"
            params = (*parameters, limit)

        if cursor is not None:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

        with (
            self._connect() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as local_cursor,
        ):
            local_cursor.execute(query, params)
            return [dict(row) for row in local_cursor.fetchall()]

    def _fetch_entry_row(self, entry_id: int, cursor: Any) -> dict[str, Any] | None:
        rows = self._fetch_entry_rows("by_id", (entry_id,), cursor=cursor)
        if not rows:
            return None
        return rows[0]

    def _build_search_filter(
        self,
        query: str,
        mode: SearchMode,
    ) -> tuple[str, tuple[object, ...]]:
        if mode == SearchMode.LITE:
            return (
                "search_lite",
                (
                    self._source.value,
                    query,
                    query,
                    DictionarySource.CORE.value,
                    query,
                ),
            )

        meaningful_query = " ".join(meaningful_tokens(query))
        effective_query = meaningful_query or query

        return (
            "search_complex",
            (
                self._source.value,
                effective_query,
                f"{effective_query}%",
                f"{effective_query}%",
            ),
        )

    def _row_to_entry(self, row: dict[str, Any]) -> DictionaryEntry:
        source = DictionarySource(str(row["source"]).strip())
        return DictionaryEntry(
            source=source,
            word=str(row["word"]).strip(),
            translation=str(row["translation"]).strip(),
            examples=tuple(row.get("examples") or ()),
            notes=tuple(row.get("notes") or ()),
            comments=str(row.get("comments") or "").strip(),
            contributor_username=self._strip_text(row.get("contributor_username")),
            contributor_first_name=self._strip_text(row.get("contributor_first_name")),
            contributor_last_name=self._strip_text(row.get("contributor_last_name")),
            banner=_USER_ENTRY_BANNER if source == DictionarySource.USER else None,
        )
