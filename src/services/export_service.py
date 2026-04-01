"""Экспорт данных из базы в Excel-файл."""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from repositories.db_repository import PostgresRepository


class DatabaseExportService:
    """Сервис выгрузки таблиц PostgreSQL во временный XLSX-файл."""

    def __init__(self, repository: PostgresRepository) -> None:
        """Сохранить репозиторий, из которого берутся данные для экспорта.

        Args:
            repository: Репозиторий с доступом к таблицам PostgreSQL.
        """
        self._repository = repository

    def export_to_tempfile(self) -> Path:
        """Собрать XLSX-файл во временной директории.

        Returns:
            Путь к созданному временному файлу с выгрузкой.
        """
        users = self._repository.fetch_users()
        actions = self._repository.fetch_actions()

        workbook = Workbook()
        users_sheet = workbook.active
        users_sheet.title = "Users"
        self._write_sheet(users_sheet, users)

        actions_sheet = workbook.create_sheet("Actions")
        self._write_sheet(actions_sheet, actions)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_file:
            temp_path = Path(temp_file.name)

        workbook.save(temp_path)
        return temp_path

    @staticmethod
    def _write_sheet(sheet: Any, rows: Sequence[Mapping[str, object]]) -> None:
        headers = list(rows[0].keys()) if rows else []
        if headers:
            sheet.append(headers)
            for row in rows:
                sheet.append([row.get(header, "") for header in headers])
            sheet.freeze_panes = "A2"
        else:
            sheet.append(["empty"])
