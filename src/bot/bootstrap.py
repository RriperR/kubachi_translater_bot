"""Сборка общих зависимостей приложения и benchmark-скриптов."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Dispatcher, Router

from config import AppConfig
from models import DictionarySource
from repositories.db_repository import PostgresRepository
from repositories.postgres import PostgresDictionaryRepository
from services.export_service import DatabaseExportService
from services.rag import PgvectorSearchProvider, build_embedding_provider
from services.search import DictionarySearchService, LexicalSearchProvider
from services.search.lexical import SearchProvider
from services.session_store import SessionStore


@dataclass(frozen=True)
class DictionaryRuntime:
    """Общие сервисы и репозитории, используемые ботом и бенчмарками."""

    db_repository: PostgresRepository
    main_repository: PostgresDictionaryRepository
    user_repository: PostgresDictionaryRepository
    search_service: DictionarySearchService
    export_service: DatabaseExportService


@dataclass(frozen=True)
class BotInfrastructure:
    """Telegram-инфраструктура поверх общих сервисов."""

    bot: Bot
    dispatcher: Dispatcher
    router: Router
    session_store: SessionStore


@dataclass(frozen=True)
class BotStack:
    """Полный стек зависимостей приложения."""

    config: AppConfig
    runtime: DictionaryRuntime
    infrastructure: BotInfrastructure


def build_runtime(config: AppConfig) -> DictionaryRuntime:
    """Собрать общие сервисы и репозитории приложения.

    Args:
        config: Корневая конфигурация приложения.

    Returns:
        Общие сервисы и репозитории для бота и benchmark-скриптов.
    """
    db_repository = PostgresRepository(config.database)
    main_repository = PostgresDictionaryRepository(config.database, DictionarySource.CORE)
    user_repository = PostgresDictionaryRepository(config.database, DictionarySource.USER)
    embedding_provider = build_embedding_provider(config)
    semantic_providers: tuple[SearchProvider, ...] = ()
    if config.rag_enabled:
        semantic_providers = (
            PgvectorSearchProvider(
                repository=main_repository,
                embedding_provider=embedding_provider,
                top_k=config.rag_top_k,
                max_distance=config.rag_max_distance,
            ),
            PgvectorSearchProvider(
                repository=user_repository,
                embedding_provider=embedding_provider,
                top_k=config.rag_top_k,
                max_distance=config.rag_max_distance,
            ),
        )
    search_service = DictionarySearchService(
        providers=(
            LexicalSearchProvider(main_repository),
            LexicalSearchProvider(user_repository),
            *semantic_providers,
        )
    )
    export_service = DatabaseExportService(db_repository)
    return DictionaryRuntime(
        db_repository=db_repository,
        main_repository=main_repository,
        user_repository=user_repository,
        search_service=search_service,
        export_service=export_service,
    )


def build_infrastructure(config: AppConfig) -> BotInfrastructure:
    """Собрать Telegram-инфраструктуру приложения.

    Args:
        config: Корневая конфигурация приложения.

    Returns:
        Telegram-бот, dispatcher, router и session store.
    """
    return BotInfrastructure(
        bot=Bot(token=config.bot_token.get_secret_value()),
        dispatcher=Dispatcher(),
        router=Router(),
        session_store=SessionStore(),
    )


def build_stack(config: AppConfig) -> BotStack:
    """Собрать полный стек зависимостей приложения.

    Args:
        config: Корневая конфигурация приложения.

    Returns:
        Полный стек зависимостей бота.
    """
    return BotStack(
        config=config,
        runtime=build_runtime(config),
        infrastructure=build_infrastructure(config),
    )
