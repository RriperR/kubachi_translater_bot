"""Приложение Telegram-бота и точка входа для polling."""

from __future__ import annotations

import asyncio
import logging

from bot.bootstrap import build_stack
from bot.handlers import DictionaryBotHandlers
from config import AppConfig, load_config

logger = logging.getLogger(__name__)


class DictionaryBotApp:
    """Основной объект aiogram-приложения."""

    def __init__(self, config: AppConfig) -> None:
        """Собрать зависимости бота и зарегистрировать обработчики.

        Args:
            config: Конфигурация приложения и пути к словарным данным.
        """
        self._stack = build_stack(config)
        self._bot = self._stack.infrastructure.bot
        self._dispatcher = self._stack.infrastructure.dispatcher
        self._router = self._stack.infrastructure.router
        self._session_store = self._stack.infrastructure.session_store
        self._runtime = self._stack.runtime
        self._config = self._stack.config
        self._handlers = DictionaryBotHandlers(
            config=self._config,
            bot=self._bot,
            runtime=self._runtime,
            session_store=self._session_store,
        )
        self._dispatcher.include_router(self._router)
        self._handlers.register(self._router)

    async def run(self) -> None:
        """Подготовить зависимости и запустить polling Telegram-бота."""
        await asyncio.to_thread(self._runtime.db_repository.require_schema)
        await asyncio.to_thread(self._runtime.main_repository.sync_rag_chunks)
        await asyncio.to_thread(self._runtime.user_repository.sync_rag_chunks)
        await self._dispatcher.start_polling(self._bot)


async def run() -> None:
    """Собрать приложение и запустить polling."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = DictionaryBotApp(load_config())
    await app.run()


def main() -> None:
    """Синхронная точка входа для локального запуска."""
    asyncio.run(run())
