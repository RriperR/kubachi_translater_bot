"""Тесты загрузки конфигурации приложения."""

from __future__ import annotations

from config import AppConfig
from services.rag import (
    HashEmbeddingProvider,
    HttpEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    build_embedding_provider,
    build_local_embedding_provider,
)


def test_app_config_loads_from_env(monkeypatch) -> None:
    """Настройки должны корректно читаться из переменных окружения."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "bot")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "kubachi_db")
    monkeypatch.setenv("LOGS_CHAT_ID", "-100123")
    monkeypatch.setenv("ADMINS_CHAT_IDS", "123456,789012")

    config = AppConfig(_env_file=None)

    assert config.bot_token.get_secret_value() == "token"
    assert config.logs_chat_id == -100123
    assert config.admins_chat_ids == (123456, 789012)
    assert config.database.host == "db"
    assert config.database.port == 5432
    assert config.database.user == "bot"
    assert config.database.password.get_secret_value() == "secret"
    assert config.database.database == "kubachi_db"
    assert config.rag_enabled is True
    assert config.rag_top_k == 5
    assert config.rag_max_distance == 0.65
    assert config.rag_index_batch_size == 1024
    assert config.rag_embedding_provider == "sentence-transformers"
    assert (
        config.rag_embedding_model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert config.rag_embedding_dimensions == 384
    assert config.rag_embedding_batch_size == 64
    assert config.rag_embedding_device == "cpu"
    assert config.rag_embedding_service_url is None
    assert config.rag_embedding_service_timeout_seconds == 15.0
    assert config.embedding_service_provider == "sentence-transformers"
    assert (
        config.embedding_service_model
        == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert config.embedding_service_dimensions == 384
    assert config.embedding_service_batch_size == 64
    assert config.embedding_service_device == "cpu"
    assert config.embedding_service_host == "127.0.0.1"
    assert config.embedding_service_port == 8080


def test_app_config_supports_legacy_admin_chat_id_as_logs_alias(monkeypatch) -> None:
    """Старый ADMIN_CHAT_ID должен оставаться alias для LOGS_CHAT_ID."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "bot")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "kubachi_db")
    monkeypatch.setenv("ADMIN_CHAT_ID", "-100555")

    config = AppConfig(_env_file=None)

    assert config.logs_chat_id == -100555
    assert config.admins_chat_ids == ()


def test_build_embedding_provider_supports_http(monkeypatch) -> None:
    """Фабрика RAG embeddings должна уметь собирать HTTP provider."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "bot")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "kubachi_db")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "http")
    monkeypatch.setenv("RAG_EMBEDDING_SERVICE_URL", "http://embeddings:8080")

    config = AppConfig(_env_file=None)
    provider = build_embedding_provider(config)

    assert isinstance(provider, HttpEmbeddingProvider)


def test_build_embedding_provider_keeps_sentence_transformers_default(monkeypatch) -> None:
    """Фабрика должна оставлять sentence-transformers провайдер по умолчанию."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "bot")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "kubachi_db")

    config = AppConfig(_env_file=None)
    provider = build_embedding_provider(config)

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)


def test_build_local_embedding_provider_supports_hash(monkeypatch) -> None:
    """Локальная фабрика embedding-сервиса должна уметь собирать hash provider."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_USER", "bot")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "kubachi_db")
    monkeypatch.setenv("EMBEDDING_SERVICE_PROVIDER", "hash")
    monkeypatch.setenv("EMBEDDING_SERVICE_DIMENSIONS", "128")

    config = AppConfig(_env_file=None)
    provider = build_local_embedding_provider(config)

    assert isinstance(provider, HashEmbeddingProvider)
    assert provider.dimensions == 128
