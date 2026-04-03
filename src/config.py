"""Конфигурация приложения и загрузка переменных окружения через pydantic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class DatabaseConfig(BaseModel):
    """Параметры подключения к PostgreSQL."""

    model_config = ConfigDict(frozen=True)

    host: str
    port: int
    user: str
    password: SecretStr
    database: str


class AppConfig(BaseSettings):
    """Корневая конфигурация приложения."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    bot_token: SecretStr
    logs_chat_id: int | None = None
    admins_chat_ids: Annotated[tuple[int, ...], NoDecode] = ()
    db_host: str
    db_port: int
    db_user: str
    db_password: SecretStr
    db_name: str
    rag_enabled: bool = True
    rag_top_k: int = 5
    rag_max_distance: float = 0.65
    rag_index_batch_size: int = 1024
    rag_embedding_provider: str = "sentence-transformers"
    rag_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    rag_embedding_dimensions: int = 384
    rag_embedding_batch_size: int = 64
    rag_embedding_device: str = "cpu"

    @field_validator("admins_chat_ids", mode="before")
    @classmethod
    def _parse_admins_chat_ids(cls, value: object) -> tuple[int, ...]:
        """Преобразовать список админов из env в кортеж chat_id.

        Args:
            value: Сырое значение из переменной окружения.

        Returns:
            Кортеж chat_id администраторов.
        """
        if value is None or value == "":
            return ()
        if isinstance(value, tuple):
            return tuple(int(item) for item in value)
        if isinstance(value, list):
            return tuple(int(item) for item in value)
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",") if part.strip()]
            return tuple(int(part) for part in parts)
        return (int(str(value)),)

    @model_validator(mode="before")
    @classmethod
    def _apply_legacy_logs_chat_alias(cls, data: object) -> object:
        """Поддержать старое имя переменной для чата логов.

        Args:
            data: Сырые входные данные до валидации настроек.

        Returns:
            Обновленные входные данные с подставленным legacy alias при необходимости.
        """
        if not isinstance(data, dict):
            return data

        if "logs_chat_id" in data or "LOGS_CHAT_ID" in data:
            return data

        legacy_value = os.getenv("ADMIN_CHAT_ID")
        if legacy_value is None or legacy_value == "":
            return data

        return {**data, "logs_chat_id": int(legacy_value)}

    @property
    def database(self) -> DatabaseConfig:
        """Собрать параметры подключения к PostgreSQL.

        Returns:
            Объект с параметрами подключения к базе данных.
        """
        return DatabaseConfig(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_password,
            database=self.db_name,
        )


def load_config() -> AppConfig:
    """Собрать конфигурацию приложения из переменных окружения.

    Returns:
        Заполненный объект конфигурации приложения.
    """
    return AppConfig()
