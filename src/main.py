"""Точка входа для локального запуска Telegram-бота."""

from __future__ import annotations

import asyncio
import logging

from bot.application import DictionaryBotApp
from config import load_config


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


if __name__ == "__main__":
    main()
