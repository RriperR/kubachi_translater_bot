"""Конфигурация приложения и загрузка переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()


@dataclass(frozen=True)
class DatabaseConfig:
    """Параметры подключения к PostgreSQL."""

    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class AppConfig:
    """Корневая конфигурация приложения."""

    bot_token: str
    admin_chat_id: int | None
    database: DatabaseConfig
    main_dictionary_path: Path
    user_dictionary_path: Path


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return int(value)


def load_config() -> AppConfig:
    """Собрать конфигурацию приложения из переменных окружения.

    Returns:
        Заполненный объект конфигурации приложения.
    """
    return AppConfig(
        bot_token=_require_env("BOT_TOKEN"),
        admin_chat_id=_optional_int("ADMIN_CHAT_ID"),
        database=DatabaseConfig(
            host=_require_env("DB_HOST"),
            port=int(_require_env("DB_PORT")),
            user=_require_env("DB_USER"),
            password=_require_env("DB_PASSWORD"),
            database=_require_env("DB_NAME"),
        ),
        main_dictionary_path=BASE_DIR / "Slovar_14_08.csv",
        user_dictionary_path=BASE_DIR / "users_translates.csv",
    )
