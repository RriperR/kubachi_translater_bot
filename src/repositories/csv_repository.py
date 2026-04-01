"""Работа с CSV-файлами словаря."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from models import DictionaryEntry, DictionarySource, TelegramUser, UserSubmittedEntry
from normalization import compact_lines, split_values


@dataclass(frozen=True)
class CsvSchema:
    """Описание структуры CSV-файла словаря."""

    fieldnames: tuple[str, ...]
    notes_columns: tuple[tuple[str, str], ...]
    comments_column: str | None
    comment_author_columns: tuple[str, str, str] | None = None
    contributor_columns: tuple[str, str, str] | None = None
    banner: str | None = None


MAIN_SCHEMA = CsvSchema(
    fieldnames=(
        "Column1",
        "Column2",
        "Column3",
        "Column4",
        "Column5",
        "Column6",
        "Column7",
        "Column8",
        "Column9",
    ),
    notes_columns=(("Column4", "\\"), ("Column5", "||")),
    comments_column="Column6",
    comment_author_columns=("Column7", "Column8", "Column9"),
)

USER_SCHEMA = CsvSchema(
    fieldnames=(
        "Column1",
        "Column2",
        "Column3",
        "Column4",
        "Column5",
        "Column6",
        "Column7",
        "Column8",
        "Column9",
        "Column10",
        "Column11",
    ),
    notes_columns=(("Column4", "\\"),),
    comments_column="Column8",
    comment_author_columns=("Column9", "Column10", "Column11"),
    contributor_columns=("Column5", "Column6", "Column7"),
    banner="!!!ПОЛЬЗОВАТЕЛЬСКИЙ ПЕРЕВОД!!!",
)


class CsvDictionaryRepository:
    """Чтение и запись словарных статей в CSV."""

    def __init__(self, path: Path, source: DictionarySource, schema: CsvSchema) -> None:
        """Подготовить репозиторий для конкретного CSV-файла.

        Args:
            path: Путь к словарному CSV-файлу.
            source: Источник статей, который будет присвоен записям.
            schema: Описание колонок и служебных полей CSV-файла.
        """
        self._path = path
        self._source = source
        self._schema = schema
        self._cached_mtime_ns: int | None = None
        self._cached_rows: list[dict[str, str]] = []

    @property
    def path(self) -> Path:
        """Вернуть путь к исходному CSV-файлу.

        Returns:
            Абсолютный или относительный путь к словарному CSV.
        """
        return self._path

    def list_entries(self) -> list[DictionaryEntry]:
        """Прочитать все статьи словаря из CSV.

        Returns:
            Список нормализованных словарных статей.
        """
        return [self._row_to_entry(row) for row in self._load_rows()]

    def append_user_entry(self, entry: UserSubmittedEntry) -> None:
        """Добавить пользовательскую статью в CSV.

        Args:
            entry: Подготовленная пользовательская статья для сохранения.
        """
        row = {field: "" for field in self._schema.fieldnames}
        row["Column1"] = entry.word
        row["Column2"] = entry.translation
        row["Column3"] = entry.phrases_raw
        row["Column4"] = entry.supporting_raw

        contributor_columns = self._schema.contributor_columns
        if contributor_columns is not None:
            username_col, first_name_col, last_name_col = contributor_columns
            row[username_col] = entry.contributor.username or ""
            row[first_name_col] = entry.contributor.first_name or ""
            row[last_name_col] = entry.contributor.last_name or ""

        self._append_row(row)

    def append_comment(self, title: str, comment: str, author: TelegramUser) -> bool:
        """Добавить комментарий к существующей статье.

        Args:
            title: Заголовок статьи в формате `слово - перевод`.
            comment: Текст комментария пользователя.
            author: Данные пользователя, оставившего комментарий.

        Returns:
            `True`, если статья найдена и обновлена, иначе `False`.
        """
        rows = self._load_rows(force_reload=True)

        for row in rows:
            if self._build_title(row) != title:
                continue

            comments_column = self._schema.comments_column
            if comments_column:
                existing_comment = row.get(comments_column, "")
                row[comments_column] = self._append_line(
                    existing_comment,
                    f"Пользователь оставил комментарий: {comment}",
                )

            author_columns = self._schema.comment_author_columns
            if author_columns is not None:
                username_col, first_name_col, last_name_col = author_columns
                row[username_col] = self._append_line(
                    row.get(username_col, ""),
                    author.username or "",
                )
                row[first_name_col] = self._append_line(
                    row.get(first_name_col, ""),
                    author.first_name or "",
                )
                row[last_name_col] = self._append_line(
                    row.get(last_name_col, ""),
                    author.last_name or "",
                )

            self._write_rows(rows)
            return True

        return False

    def _load_rows(self, force_reload: bool = False) -> list[dict[str, str]]:
        mtime_ns = self._path.stat().st_mtime_ns
        if not force_reload and self._cached_mtime_ns == mtime_ns:
            return [row.copy() for row in self._cached_rows]

        with self._path.open("r", encoding="cp1251", errors="replace", newline="") as file:
            reader = csv.DictReader(file, delimiter=";")
            rows = [{key: value or "" for key, value in row.items()} for row in reader]

        self._cached_rows = rows
        self._cached_mtime_ns = mtime_ns
        return [row.copy() for row in rows]

    def _append_row(self, row: dict[str, str]) -> None:
        file_exists = self._path.exists() and self._path.stat().st_size > 0
        with self._path.open("a", encoding="cp1251", errors="replace", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=self._schema.fieldnames,
                delimiter=";",
                lineterminator="\n",
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        self._invalidate_cache()

    def _write_rows(self, rows: list[dict[str, str]]) -> None:
        with self._path.open("w", encoding="cp1251", errors="replace", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=self._schema.fieldnames,
                delimiter=";",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in rows:
                normalized_row = {field: row.get(field, "") for field in self._schema.fieldnames}
                writer.writerow(normalized_row)
        self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        self._cached_mtime_ns = None
        self._cached_rows = []

    def _row_to_entry(self, row: dict[str, str]) -> DictionaryEntry:
        notes: list[str] = []
        for column, separator in self._schema.notes_columns:
            notes.extend(split_values(row.get(column, ""), separator))

        contributor_username = None
        contributor_first_name = None
        contributor_last_name = None
        contributor_columns = self._schema.contributor_columns
        if contributor_columns is not None:
            username_col, first_name_col, last_name_col = contributor_columns
            contributor_username = row.get(username_col) or None
            contributor_first_name = row.get(first_name_col) or None
            contributor_last_name = row.get(last_name_col) or None

        comments = ""
        if self._schema.comments_column:
            comments = row.get(self._schema.comments_column, "").strip()

        return DictionaryEntry(
            source=self._source,
            word=row.get("Column1", "").strip(),
            translation=row.get("Column2", "").strip(),
            examples=compact_lines(split_values(row.get("Column3", ""), "%")),
            notes=compact_lines(notes),
            comments=comments,
            contributor_username=contributor_username,
            contributor_first_name=contributor_first_name,
            contributor_last_name=contributor_last_name,
            banner=self._schema.banner,
        )

    @staticmethod
    def _build_title(row: dict[str, str]) -> str:
        return f"{row.get('Column1', '').strip()} - {row.get('Column2', '').strip()}"

    @staticmethod
    def _append_line(existing: str, value: str) -> str:
        if not value:
            return existing
        if existing.strip():
            return existing.rstrip("\n") + "\n" + value
        return value
