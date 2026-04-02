"""Конфигурация приложения и загрузка переменных окружения через pydantic."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent


class DatabaseConfig(BaseModel):
    """Параметры подключения к PostgreSQL."""

    model_config = ConfigDict(frozen=True)

    host: str
    port: int
    user: str
    password: str
    database: str


class AppConfig(BaseSettings):
    """Корневая конфигурация приложения."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    bot_token: str = Field(validation_alias="BOT_TOKEN")
    admin_chat_id: int | None = Field(default=None, validation_alias="ADMIN_CHAT_ID")
    db_host: str = Field(validation_alias="DB_HOST", exclude=True)
    db_port: int = Field(validation_alias="DB_PORT", exclude=True)
    db_user: str = Field(validation_alias="DB_USER", exclude=True)
    db_password: str = Field(validation_alias="DB_PASSWORD", exclude=True, repr=False)
    db_name: str = Field(validation_alias="DB_NAME", exclude=True)
    main_dictionary_path: Path = BASE_DIR / "Slovar_14_08.csv"
    user_dictionary_path: Path = BASE_DIR / "users_translates.csv"

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
