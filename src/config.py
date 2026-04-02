"""Конфигурация приложения и загрузка переменных окружения через pydantic."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    admin_chat_id: int | None = None
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
