"""Тесты загрузки конфигурации приложения."""

from __future__ import annotations

from config import AppConfig


def test_app_config_loads_from_env(monkeypatch) -> None:
    """Настройки должны корректно читаться из переменных окружения."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "bot")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "kubachi_db")
    monkeypatch.setenv("ADMIN_CHAT_ID", "-100123")

    config = AppConfig()

    assert config.bot_token.get_secret_value() == "token"
    assert config.admin_chat_id == -100123
    assert config.database.host == "db"
    assert config.database.port == 5432
    assert config.database.user == "bot"
    assert config.database.password.get_secret_value() == "secret"
    assert config.database.database == "kubachi_db"
