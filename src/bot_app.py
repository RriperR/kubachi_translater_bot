"""Точка входа Telegram-бота и его обработчики."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import texts
from config import AppConfig, load_config
from models import DictionarySource, SearchMode, TelegramUser, UserSubmittedEntry
from normalization import normalize_kubachi_word
from repositories.db_repository import PostgresRepository
from repositories.postgres_dictionary_repository import PostgresDictionaryRepository
from services.export_service import DatabaseExportService
from services.rag_service import PgvectorSearchProvider, build_embedding_provider
from services.search_service import CsvSearchProvider, DictionarySearchService, format_entry
from services.session_store import SessionStore

logger = logging.getLogger(__name__)


class AddEntryFlow(StatesGroup):
    """Состояния диалога для добавления пользовательской статьи."""

    word = State()
    translation = State()
    phrases = State()
    supporting = State()
    confirm = State()


class CommentFlow(StatesGroup):
    """Состояние диалога для добавления комментария."""

    text = State()


class DictionaryBotApp:
    """Основной объект aiogram-приложения."""

    def __init__(self, config: AppConfig) -> None:
        """Собрать зависимости бота и зарегистрировать обработчики.

        Args:
            config: Конфигурация приложения и пути к словарным данным.
        """
        self._config = config
        self._bot = Bot(token=config.bot_token.get_secret_value())
        self._dispatcher = Dispatcher()
        self._router = Router()
        self._dispatcher.include_router(self._router)

        self._session_store = SessionStore()
        self._db_repository = PostgresRepository(
            config.database,
            rag_vector_dimensions=config.rag_embedding_dimensions,
        )
        self._main_repository = PostgresDictionaryRepository(config.database, DictionarySource.CORE)
        self._user_repository = PostgresDictionaryRepository(config.database, DictionarySource.USER)
        self._embedding_provider = build_embedding_provider(config)
        semantic_providers: tuple[Any, ...] = ()
        if config.rag_enabled:
            semantic_providers = (
                PgvectorSearchProvider(
                    repository=self._main_repository,
                    embedding_provider=self._embedding_provider,
                    top_k=config.rag_top_k,
                    max_distance=config.rag_max_distance,
                ),
                PgvectorSearchProvider(
                    repository=self._user_repository,
                    embedding_provider=self._embedding_provider,
                    top_k=config.rag_top_k,
                    max_distance=config.rag_max_distance,
                ),
            )
        self._search_service = DictionarySearchService(
            providers=(
                CsvSearchProvider(self._main_repository),
                CsvSearchProvider(self._user_repository),
                *semantic_providers,
            )
        )
        self._export_service = DatabaseExportService(self._db_repository)

        self._register_handlers()

    async def run(self) -> None:
        """Подготовить зависимости и запустить polling Telegram-бота."""
        await asyncio.to_thread(self._db_repository.ensure_schema)
        await asyncio.to_thread(self._main_repository.sync_rag_chunks)
        await asyncio.to_thread(self._user_repository.sync_rag_chunks)
        await self._dispatcher.start_polling(self._bot)

    def _register_handlers(self) -> None:
        self._router.message.register(self._handle_start, Command("start"))
        self._router.message.register(self._handle_restart, Command("restart"))
        self._router.message.register(self._handle_help, Command("help"))
        self._router.message.register(self._handle_info, Command("info"))
        self._router.message.register(self._handle_chat_id, Command("chatid"))
        self._router.message.register(self._handle_getdb, Command("getdb"))
        self._router.message.register(self._handle_add_command, Command("add"))
        self._router.message.register(self._handle_comment_command, Command("comment"))
        self._router.message.register(self._handle_mode_command, Command("mode"))

        self._router.message.register(self._handle_add_word, AddEntryFlow.word)
        self._router.message.register(self._handle_add_translation, AddEntryFlow.translation)
        self._router.message.register(self._handle_add_phrases, AddEntryFlow.phrases)
        self._router.message.register(self._handle_add_supporting, AddEntryFlow.supporting)
        self._router.message.register(self._handle_add_confirm, AddEntryFlow.confirm)
        self._router.message.register(self._handle_comment_text, CommentFlow.text)

        self._router.callback_query.register(self._handle_mode_callback, F.data.startswith("mode:"))
        self._router.callback_query.register(self._handle_page_callback, F.data.startswith("page:"))
        self._router.message.register(self._handle_search, F.text & ~F.text.startswith("/"))

    async def _handle_start(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        self._session_store.reset(message.chat.id)
        await self._track_message(message, "/start")
        await message.answer(texts.WELCOME_TEXT)
        await message.answer(texts.ENTER_WORD_TEXT)
        await self._notify_admin(
            f"Пользователь {self._format_actor(message)} использовал команду /start"
        )

    async def _handle_restart(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        self._session_store.reset(message.chat.id)
        await self._track_message(message, "/restart")
        await message.answer(texts.WELCOME_TEXT)
        await message.answer(texts.ENTER_WORD_TEXT)
        await self._notify_admin(
            f"Пользователь {self._format_actor(message)} использовал команду /restart"
        )

    async def _handle_help(self, message: Message) -> None:
        await self._track_message(message, "/help")
        await message.answer(texts.HELP_TEXT)

    async def _handle_info(self, message: Message) -> None:
        await self._track_message(message, "/info")
        await message.answer(texts.INFO_TEXT)

    async def _handle_chat_id(self, message: Message) -> None:
        await message.answer(f"Ваш chat_id: {message.chat.id}")

    async def _handle_getdb(self, message: Message) -> None:
        await self._track_message(message, "/getdb")
        if not self._is_admin(message.chat.id):
            await message.answer(texts.ADMIN_ONLY_TEXT)
            return

        temp_path: Path | None = None
        try:
            temp_path = await asyncio.to_thread(self._export_service.export_to_tempfile)
            await message.answer_document(FSInputFile(temp_path), caption=texts.EXPORT_CAPTION)
        except Exception as exc:  # pragma: no cover
            await self._handle_failure(message.chat.id, exc)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    async def _handle_add_command(self, message: Message, state: FSMContext) -> None:
        await self._track_message(message, "/add")
        await state.clear()
        await state.set_state(AddEntryFlow.word)
        await message.answer(texts.ADD_GUIDE_TEXT)
        await message.answer(texts.ADD_WORD_PROMPT)

    async def _handle_add_word(self, message: Message, state: FSMContext) -> None:
        await state.update_data(word=normalize_kubachi_word(message.text or ""))
        await state.set_state(AddEntryFlow.translation)
        await message.answer(texts.ADD_TRANSLATION_PROMPT)

    async def _handle_add_translation(self, message: Message, state: FSMContext) -> None:
        await state.update_data(translation=(message.text or "").strip())
        await state.set_state(AddEntryFlow.phrases)
        await message.answer(texts.ADD_PHRASES_PROMPT)

    async def _handle_add_phrases(self, message: Message, state: FSMContext) -> None:
        await state.update_data(phrases=(message.text or "").strip())
        await state.set_state(AddEntryFlow.supporting)
        await message.answer(texts.ADD_SUPPORTING_PROMPT)

    async def _handle_add_supporting(self, message: Message, state: FSMContext) -> None:
        supporting = (message.text or "").strip()
        if supporting == "0":
            supporting = ""

        await state.update_data(supporting=supporting)
        data = await state.get_data()
        preview = self._build_entry_preview(
            data.get("word", ""),
            data.get("translation", ""),
            data.get("phrases", ""),
            supporting,
        )
        await state.set_state(AddEntryFlow.confirm)
        await message.answer(preview)
        await message.answer(texts.ADD_CONFIRM_PROMPT)

    async def _handle_add_confirm(self, message: Message, state: FSMContext) -> None:
        answer = (message.text or "").strip().lower()
        if answer == "нет":
            await state.clear()
            await message.answer(texts.ADD_CANCELLED_TEXT)
            return

        if answer != "да":
            await message.answer(texts.ADD_INVALID_CONFIRM_TEXT)
            return

        data = await state.get_data()
        if not data:
            await state.clear()
            await message.answer(texts.ADD_STATE_MISSING_TEXT)
            return

        submission = UserSubmittedEntry(
            word=data.get("word", ""),
            translation=data.get("translation", ""),
            phrases_raw=data.get("phrases", ""),
            supporting_raw=data.get("supporting", ""),
            contributor=self._extract_actor(message),
        )

        try:
            await asyncio.to_thread(self._user_repository.append_user_entry, submission)
            await asyncio.to_thread(
                self._db_repository.log_action,
                f'ADD "{submission.word} - {submission.translation}"',
                message.chat.id,
            )
            await message.answer(texts.ADD_SUCCESS_TEXT)
        except Exception as exc:  # pragma: no cover
            await self._handle_failure(message.chat.id, exc)
        finally:
            await state.clear()

    async def _handle_comment_command(self, message: Message, state: FSMContext) -> None:
        await self._track_message(message, "/comment")

        if not message.reply_to_message or not message.reply_to_message.text:
            await message.answer(texts.COMMENT_NEEDS_REPLY_TEXT)
            return

        target = self._extract_comment_target(message.reply_to_message.text)
        if target is None:
            await message.answer(texts.COMMENT_NOT_FOUND_TEXT)
            return

        source, title = target
        await state.clear()
        await state.set_state(CommentFlow.text)
        await state.update_data(comment_source=source.value, comment_title=title)
        await message.answer(texts.COMMENT_PROMPT)

    async def _handle_comment_text(self, message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        if not data:
            await state.clear()
            await message.answer(texts.COMMENT_STATE_MISSING_TEXT)
            return

        source = DictionarySource(data["comment_source"])
        title = data["comment_title"]
        repository = (
            self._user_repository if source == DictionarySource.USER else self._main_repository
        )

        try:
            updated = await asyncio.to_thread(
                repository.append_comment,
                title,
                (message.text or "").strip(),
                self._extract_actor(message),
            )
            await message.answer(
                texts.COMMENT_SUCCESS_TEXT if updated else texts.COMMENT_NOT_FOUND_TEXT
            )
        except Exception as exc:  # pragma: no cover
            await self._handle_failure(message.chat.id, exc)
        finally:
            await state.clear()

    async def _handle_mode_command(self, message: Message) -> None:
        await self._track_message(message, "/mode")
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Простой", callback_data="mode:lite"),
                    InlineKeyboardButton(text="Комплексный", callback_data="mode:complex"),
                ]
            ]
        )
        await message.answer(texts.MODE_PROMPT_TEXT, reply_markup=markup)

    async def _handle_mode_callback(self, callback: CallbackQuery) -> None:
        await callback.answer()
        source_message = callback.message
        if source_message is None:
            return

        mode = SearchMode.from_value((callback.data or "").split(":", 1)[1])
        actor = self._extract_actor_from_callback(callback)

        try:
            await asyncio.to_thread(self._db_repository.ensure_user, actor)
            await asyncio.to_thread(self._db_repository.update_user_mode, actor.chat_id, mode)
            await source_message.answer(
                texts.MODE_COMPLEX_TEXT if mode == SearchMode.COMPLEX else texts.MODE_LITE_TEXT
            )
        except Exception as exc:  # pragma: no cover
            await self._handle_failure(actor.chat_id, exc, user_message=texts.MODE_ERROR_TEXT)

    async def _handle_page_callback(self, callback: CallbackQuery) -> None:
        await callback.answer()
        source_message = callback.message
        if source_message is None:
            return

        if callback.data == "page:stop":
            self._session_store.reset(source_message.chat.id)
            await source_message.answer(texts.NO_MORE_RESULTS_TEXT)
            return

        await self._send_next_page(source_message.chat.id)

    async def _handle_search(self, message: Message, state: FSMContext) -> None:
        if await state.get_state() is not None:
            return

        query = (message.text or "").strip()
        if not query:
            return

        await self._track_message(message, f'"{query}"')
        await self._notify_admin(f'Пользователь {self._format_actor(message)} ищет "{query}"')

        try:
            mode = await asyncio.to_thread(self._db_repository.get_user_mode, message.chat.id)
            entries = await asyncio.to_thread(self._search_service.search, query, mode)
        except Exception as exc:  # pragma: no cover
            await self._handle_failure(message.chat.id, exc)
            return

        if not entries:
            not_found_text = (
                texts.SEARCH_NOT_FOUND_COMPLEX_TEXT
                if mode == SearchMode.COMPLEX
                else texts.SEARCH_NOT_FOUND_LITE_TEXT
            )
            await message.answer(not_found_text)
            return

        if len(entries) > 100:
            await message.answer(texts.SEARCH_TOO_MANY_TEXT)
            self._session_store.reset(message.chat.id)
            return

        session = self._session_store.get(message.chat.id)
        session.pending_results = [format_entry(entry) for entry in entries]

        await message.answer(f"Всего {len(session.pending_results)} совпадений.")
        await self._send_next_page(message.chat.id)

    async def _send_next_page(self, chat_id: int) -> None:
        session = self._session_store.get(chat_id)
        batch = session.pending_results[:10]
        session.pending_results = session.pending_results[10:]

        if not batch:
            await self._bot.send_message(chat_id, texts.NO_MORE_RESULTS_TEXT)
            return

        for item in batch:
            await self._bot.send_message(chat_id, item)

        if session.pending_results:
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Да", callback_data="page:more"),
                        InlineKeyboardButton(text="Нет", callback_data="page:stop"),
                    ]
                ]
            )
            await self._bot.send_message(chat_id, texts.PAGINATION_TEXT, reply_markup=markup)
            return

        await self._bot.send_message(chat_id, texts.COMMENT_HINT_TEXT)

    async def _track_message(self, message: Message, action: str) -> None:
        actor = self._extract_actor(message)
        try:
            await asyncio.to_thread(self._db_repository.ensure_user, actor)
            await asyncio.to_thread(self._db_repository.log_action, action, actor.chat_id)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to track message")
            await self._notify_admin(f"Ошибка логирования: {exc}")

    async def _handle_failure(
        self,
        chat_id: int,
        exc: Exception,
        user_message: str = texts.GENERIC_ERROR_TEXT,
    ) -> None:
        logger.exception("Bot handler failed")
        await self._notify_admin(f"Ошибка: {exc}")
        await self._bot.send_message(chat_id, user_message)

    async def _notify_admin(self, text: str) -> None:
        if self._config.admin_chat_id is None:
            return
        try:
            await self._bot.send_message(self._config.admin_chat_id, text)
        except Exception:  # pragma: no cover
            logger.exception("Failed to notify admin")

    def _extract_actor(self, message: Message) -> TelegramUser:
        from_user = message.from_user
        return TelegramUser(
            chat_id=message.chat.id,
            username=from_user.username if from_user else None,
            first_name=(from_user.first_name if from_user else "") or "",
            last_name=(from_user.last_name if from_user else "") or "",
        )

    def _extract_actor_from_callback(self, callback: CallbackQuery) -> TelegramUser:
        source_message = callback.message
        chat_id = source_message.chat.id if source_message else callback.from_user.id
        return TelegramUser(
            chat_id=chat_id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name or "",
            last_name=callback.from_user.last_name or "",
        )

    @staticmethod
    def _build_entry_preview(word: str, translation: str, phrases: str, supporting: str) -> str:
        lines = [f"{word} - {translation}", ""]
        lines.extend(part.strip() for part in phrases.split("%") if part.strip())
        if supporting.strip():
            lines.append("")
            lines.extend(part.strip() for part in supporting.split("\\") if part.strip())
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_comment_target(text: str) -> tuple[DictionarySource, str] | None:
        source = (
            DictionarySource.USER
            if text.startswith(texts.USER_ENTRY_BANNER)
            else DictionarySource.CORE
        )
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line == texts.USER_ENTRY_BANNER:
                continue
            if " - " in line:
                return source, line
        return None

    def _is_admin(self, chat_id: int) -> bool:
        return self._config.admin_chat_id is not None and chat_id == self._config.admin_chat_id

    @staticmethod
    def _format_actor(message: Message) -> str:
        from_user = message.from_user
        if from_user is None:
            return str(message.chat.id)
        username = f"@{from_user.username}" if from_user.username else str(message.chat.id)
        return f'{username} "{from_user.first_name}"'


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
