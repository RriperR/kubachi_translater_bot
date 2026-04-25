"""Обработчики Telegram-бота."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import texts
from config import AppConfig
from models import (
    AdminSuggestion,
    BroadcastAudience,
    BroadcastDeliveryStatus,
    BroadcastProgress,
    BroadcastRecipient,
    DictionaryEntry,
    DictionarySource,
    ScoreBoard,
    ScoreEntry,
    ScoreNamePolicy,
    ScorePeriod,
    SearchMode,
    TelegramUser,
    UserProfileStats,
    UserSubmittedEntry,
)
from normalization import normalize_kubachi_word
from services.search import SearchResult, format_entry
from services.session_store import SessionStore

from .bootstrap import DictionaryRuntime
from .flows import (
    AddEntryFlow,
    AdminBroadcastFlow,
    AdminCommentsFlow,
    AdminEntriesFlow,
    CommentFlow,
    ScoreAliasFlow,
    SuggestionFlow,
)

logger = logging.getLogger(__name__)


class DictionaryBotHandlers:
    """Обработчики Telegram-бота и все связанные служебные методы."""

    _ADMIN_PAGE_SIZE = 5

    def __init__(
        self,
        config: AppConfig,
        bot: Bot,
        runtime: DictionaryRuntime,
        session_store: SessionStore,
    ) -> None:
        """Собрать зависимости обработчиков.

        Args:
            config: Корневая конфигурация приложения.
            bot: Telegram-бот.
            runtime: Общие сервисы и репозитории.
            session_store: Хранилище состояния пагинации.
        """
        self._config = config
        self._bot = bot
        self._db_repository = runtime.db_repository
        self._main_repository = runtime.main_repository
        self._user_repository = runtime.user_repository
        self._search_service = runtime.search_service
        self._export_service = runtime.export_service
        self._session_store = session_store
        self._pending_broadcast_media_groups: dict[tuple[int, str], list[Message]] = {}
        self._pending_broadcast_media_group_tasks: dict[tuple[int, str], asyncio.Task[None]] = {}

    def register(self, router: Router) -> None:
        """Зарегистрировать все обработчики на router.

        Args:
            router: Router aiogram.
        """
        router.message.register(self._handle_start, Command("start"))
        router.message.register(self._handle_restart, Command("restart"))
        router.message.register(self._handle_help, Command("help"))
        router.message.register(self._handle_info, Command("info"))
        router.message.register(self._handle_me, Command("me"))
        router.message.register(self._handle_score_command, Command("score"))
        router.message.register(self._handle_chat_id, Command("chatid"))
        router.message.register(self._handle_getdb, Command("getdb"))
        router.message.register(self._handle_admin_command, Command("admin"))
        router.message.register(self._handle_add_command, Command("add"))
        router.message.register(self._handle_comment_command, Command("comment"))
        router.message.register(self._handle_suggest_command, Command("suggest"))
        router.message.register(self._handle_suggest_command, Command("idea"))
        router.message.register(self._handle_mode_command, Command("mode"))

        router.message.register(self._handle_add_word, AddEntryFlow.word)
        router.message.register(self._handle_add_translation, AddEntryFlow.translation)
        router.message.register(self._handle_add_phrases, AddEntryFlow.phrases)
        router.message.register(self._handle_add_supporting, AddEntryFlow.supporting)
        router.message.register(self._handle_add_confirm, AddEntryFlow.confirm)
        router.message.register(self._handle_comment_text, CommentFlow.text)
        router.message.register(self._handle_suggestion_text, SuggestionFlow.text)
        router.message.register(self._handle_score_alias_text, ScoreAliasFlow.name)
        router.message.register(self._handle_admin_broadcast_text, AdminBroadcastFlow.text)
        router.message.register(self._handle_admin_broadcast_days, AdminBroadcastFlow.days)
        router.message.register(self._handle_admin_entry_input, AdminEntriesFlow.filter_value)
        router.message.register(self._handle_admin_entry_input, AdminEntriesFlow.edit_value)
        router.message.register(self._handle_admin_comment_input, AdminCommentsFlow.filter_value)

        router.callback_query.register(self._handle_mode_callback, F.data.startswith("mode:"))
        router.callback_query.register(self._handle_page_callback, F.data.startswith("page:"))
        router.callback_query.register(
            self._handle_suggestion_callback,
            F.data.startswith("suggest:"),
        )
        router.callback_query.register(self._handle_score_callback, F.data.startswith("score:"))
        router.callback_query.register(self._handle_admin_callback, F.data.startswith("admin:"))
        router.message.register(self._handle_search, F.text & ~F.text.startswith("/"))

    async def _handle_start(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        self._session_store.reset(message.chat.id)
        await self._track_message(message, "/start")
        await message.answer(texts.WELCOME_TEXT)
        await message.answer(texts.ENTER_WORD_TEXT)

    async def _handle_restart(self, message: Message, state: FSMContext) -> None:
        await state.clear()
        self._session_store.reset(message.chat.id)
        await self._track_message(message, "/restart")
        await message.answer(texts.WELCOME_TEXT)
        await message.answer(texts.ENTER_WORD_TEXT)

    async def _handle_help(self, message: Message) -> None:
        await self._track_message(message, "/help")
        await message.answer(texts.HELP_TEXT)

    async def _handle_info(self, message: Message) -> None:
        await self._track_message(message, "/info")
        await message.answer(texts.INFO_TEXT)

    async def _handle_me(self, message: Message) -> None:
        await self._track_message(message, "/me")
        actor = self._extract_actor(message)
        await asyncio.to_thread(self._db_repository.ensure_user, actor)
        profile = await asyncio.to_thread(
            self._db_repository.fetch_user_profile_stats,
            actor.chat_id,
        )
        if profile is None:
            await message.answer(texts.ME_EMPTY_TEXT)
            return
        await message.answer(self._build_user_profile_summary(profile))

    async def _handle_score_command(self, message: Message) -> None:
        await self._track_message(message, "/score")
        actor = self._extract_actor(message)
        await asyncio.to_thread(self._db_repository.ensure_user, actor)
        await self._show_scoreboard(message.chat.id)

    async def _handle_chat_id(self, message: Message) -> None:
        await self._track_message(message, "/chatid")
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

    async def _handle_admin_command(self, message: Message, state: FSMContext) -> None:
        await self._track_message(message, "/admin")
        if not self._is_admin(message.chat.id):
            await message.answer(texts.ADMIN_ONLY_TEXT)
            return
        await state.clear()
        await message.answer(texts.ADMIN_ROOT_TEXT, reply_markup=self._admin_root_markup())

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
                f"/add saved: {submission.word} - {submission.translation}",
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

    async def _handle_suggest_command(self, message: Message, state: FSMContext) -> None:
        await self._track_message(message, "/suggest")
        if self._config.logs_chat_id is None:
            await message.answer(texts.SUGGEST_UNAVAILABLE_TEXT)
            return

        await state.clear()
        await state.set_state(SuggestionFlow.text)
        await message.answer(
            texts.SUGGEST_PROMPT_TEXT,
            reply_markup=self._suggest_cancel_markup(),
        )

    async def _handle_suggestion_text(self, message: Message, state: FSMContext) -> None:
        suggestion_text = (message.text or "").strip()
        if not suggestion_text:
            await message.answer(texts.SUGGEST_EMPTY_TEXT)
            return

        try:
            actor = self._extract_actor(message)
            suggestion_id = await asyncio.to_thread(
                self._db_repository.insert_suggestion,
                actor,
                suggestion_text,
            )
            await self._notify_admin(
                self._build_suggestion_notification(
                    actor,
                    suggestion_text,
                    suggestion_id,
                )
            )
            await asyncio.to_thread(
                self._db_repository.log_action,
                "/suggest sent",
                message.chat.id,
            )
            await message.answer(texts.SUGGEST_SUCCESS_TEXT)
        except Exception as exc:  # pragma: no cover
            await self._handle_failure(message.chat.id, exc)
        finally:
            await state.clear()

    async def _handle_suggestion_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        """Обработать inline-действия сценария `/suggest`.

        Args:
            callback: CallbackQuery от inline-кнопки.
            state: FSM-контекст текущего пользователя.
        """
        await callback.answer()
        message_obj = callback.message
        if not isinstance(message_obj, Message):
            return
        if callback.data != "suggest:cancel":
            return

        await state.clear()
        await message_obj.answer(texts.SUGGEST_CANCELLED_TEXT)

    async def _handle_score_callback(self, callback: CallbackQuery, state: FSMContext) -> None:
        """Обработать inline-действия команды `/score`.

        Args:
            callback: CallbackQuery от inline-кнопки.
            state: FSM-контекст текущего пользователя.
        """
        await callback.answer()
        message_obj = callback.message
        if not isinstance(message_obj, Message):
            return

        actor = self._extract_actor_from_callback(callback)
        data = callback.data or ""
        await asyncio.to_thread(self._db_repository.ensure_user, actor)

        period = self._score_period_from_callback(data)

        if data.startswith("score:period:") or data.startswith("score:refresh"):
            await self._show_scoreboard(actor.chat_id, period)
            return
        if data.startswith("score:telegram"):
            await asyncio.to_thread(
                self._db_repository.update_score_display_name,
                actor.chat_id,
                ScoreNamePolicy.TELEGRAM,
                None,
            )
            await message_obj.answer(texts.SCORE_SHOW_TELEGRAM_SUCCESS_TEXT)
            await self._show_scoreboard(actor.chat_id, period)
            return
        if data.startswith("score:anonymous"):
            await asyncio.to_thread(
                self._db_repository.update_score_display_name,
                actor.chat_id,
                ScoreNamePolicy.ANONYMOUS,
                None,
            )
            await message_obj.answer(texts.SCORE_HIDE_SUCCESS_TEXT)
            await self._show_scoreboard(actor.chat_id, period)
            return
        if data.startswith("score:custom"):
            await state.set_state(ScoreAliasFlow.name)
            await state.update_data(score_period=period.value)
            await message_obj.answer(texts.SCORE_ALIAS_PROMPT_TEXT)

    async def _handle_score_alias_text(self, message: Message, state: FSMContext) -> None:
        alias = self._normalize_score_alias(message.text or "")
        if alias is None:
            await message.answer(texts.SCORE_ALIAS_ERROR_TEXT)
            return

        actor = self._extract_actor(message)
        await asyncio.to_thread(self._db_repository.ensure_user, actor)
        await asyncio.to_thread(
            self._db_repository.update_score_display_name,
            actor.chat_id,
            ScoreNamePolicy.CUSTOM,
            alias,
        )
        data = await state.get_data()
        period = ScorePeriod(str(data.get("score_period") or ScorePeriod.ALL_TIME.value))
        await state.clear()
        await message.answer(texts.SCORE_ALIAS_SUCCESS_TEXT.format(alias=alias))
        await self._show_scoreboard(actor.chat_id, period)

    async def _handle_admin_callback(self, callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        message_obj = callback.message
        if not isinstance(message_obj, Message):
            return
        message = message_obj
        if not self._is_admin(message.chat.id):
            await message.answer(texts.ADMIN_ONLY_TEXT)
            return

        data = callback.data or ""
        if data == "admin:root":
            await state.clear()
            await message.answer(texts.ADMIN_ROOT_TEXT, reply_markup=self._admin_root_markup())
            return
        if data == "admin:stats":
            await self._show_admin_stats(message.chat.id)
            return
        if data == "admin:broadcast":
            await state.clear()
            await state.set_state(AdminBroadcastFlow.text)
            await message.answer(texts.ADMIN_BROADCAST_TEXT_PROMPT)
            return
        if data.startswith("admin:broadcast:audience:"):
            await self._handle_broadcast_audience_callback(message, state, data)
            return
        if data == "admin:broadcast:edit":
            await state.set_state(AdminBroadcastFlow.text)
            await message.answer(texts.ADMIN_BROADCAST_TEXT_PROMPT)
            return
        if data == "admin:broadcast:send":
            await self._send_broadcast(message.chat.id, state)
            return
        if data.startswith("admin:broadcast:retry:"):
            await self._retry_broadcast(message.chat.id, int(data.rsplit(":", 1)[1]))
            return
        if data == "admin:broadcast:cancel":
            await state.clear()
            await message.answer(texts.ADMIN_CANCELLED_TEXT, reply_markup=self._admin_root_markup())
            return
        if data == "admin:entries":
            await self._show_admin_entries_page(message.chat.id, state, offset=0)
            return
        if data.startswith("admin:entries:page:"):
            await self._show_admin_entries_page(
                message.chat.id,
                state,
                offset=int(data.rsplit(":", 1)[1]),
            )
            return
        if data == "admin:entries:filter:word":
            await state.set_state(AdminEntriesFlow.filter_value)
            await state.update_data(admin_entries_input_mode="word_filter")
            await message.answer(texts.ADMIN_ENTRIES_WORD_FILTER_PROMPT)
            return
        if data == "admin:entries:filter:author":
            await state.set_state(AdminEntriesFlow.filter_value)
            await state.update_data(admin_entries_input_mode="author_filter")
            await message.answer(texts.ADMIN_ENTRIES_AUTHOR_FILTER_PROMPT)
            return
        if data == "admin:entries:filters:clear":
            await state.update_data(
                admin_entries_word_filter=None,
                admin_entries_author_filter=None,
            )
            await self._show_admin_entries_page(message.chat.id, state, offset=0)
            return
        if data == "admin:entries:open":
            await state.set_state(AdminEntriesFlow.filter_value)
            await state.update_data(admin_entries_input_mode="open")
            await message.answer(texts.ADMIN_ENTRIES_OPEN_PROMPT)
            return
        if data.startswith("admin:entries:open:"):
            await self._show_admin_entry_details(message.chat.id, int(data.rsplit(":", 1)[1]))
            return
        if data.startswith("admin:entries:edit:"):
            _, _, _, entry_id_text, field_name = data.split(":", 4)
            await state.set_state(AdminEntriesFlow.edit_value)
            await state.update_data(
                admin_entries_input_mode="edit",
                admin_edit_entry_id=int(entry_id_text),
                admin_edit_field=field_name,
            )
            await message.answer(self._edit_prompt_for_field(field_name))
            return
        if data.startswith("admin:entries:delete:"):
            entry_id = int(data.rsplit(":", 1)[1])
            await message.answer(
                texts.ADMIN_ENTRIES_DELETE_CONFIRM_TEXT.format(entry_id=entry_id),
                reply_markup=self._confirm_delete_entry_markup(entry_id),
            )
            return
        if data.startswith("admin:entries:delete_confirm:"):
            entry_id = int(data.rsplit(":", 1)[1])
            deleted = await asyncio.to_thread(self._user_repository.delete_user_entry, entry_id)
            await message.answer(
                texts.ADMIN_ENTRIES_DELETE_SUCCESS_TEXT
                if deleted
                else texts.ADMIN_ENTRIES_NOT_FOUND_TEXT
            )
            await self._show_admin_entries_page(message.chat.id, state, offset=0)
            return
        if data == "admin:comments":
            await self._show_admin_comments_page(message.chat.id, state, offset=0)
            return
        if data.startswith("admin:comments:page:"):
            await self._show_admin_comments_page(
                message.chat.id,
                state,
                offset=int(data.rsplit(":", 1)[1]),
            )
            return
        if data == "admin:comments:filter:entry":
            await state.set_state(AdminCommentsFlow.filter_value)
            await state.update_data(admin_comments_input_mode="entry_filter")
            await message.answer(texts.ADMIN_COMMENTS_ENTRY_FILTER_PROMPT)
            return
        if data == "admin:comments:filter:author":
            await state.set_state(AdminCommentsFlow.filter_value)
            await state.update_data(admin_comments_input_mode="author_filter")
            await message.answer(texts.ADMIN_COMMENTS_AUTHOR_FILTER_PROMPT)
            return
        if data == "admin:comments:filters:clear":
            await state.update_data(
                admin_comments_entry_filter=None,
                admin_comments_author_filter=None,
            )
            await self._show_admin_comments_page(message.chat.id, state, offset=0)
            return
        if data == "admin:comments:delete":
            await state.set_state(AdminCommentsFlow.filter_value)
            await state.update_data(admin_comments_input_mode="delete")
            await message.answer(texts.ADMIN_COMMENTS_DELETE_PROMPT)
            return
        if data.startswith("admin:comments:delete:"):
            comment_id = int(data.rsplit(":", 1)[1])
            deleted = await asyncio.to_thread(self._main_repository.delete_comment, comment_id)
            await message.answer(
                texts.ADMIN_COMMENTS_DELETE_SUCCESS_TEXT
                if deleted
                else texts.ADMIN_COMMENTS_NOT_FOUND_TEXT
            )
            await self._show_admin_comments_page(message.chat.id, state, offset=0)
            return
        if data == "admin:suggestions":
            await self._show_admin_suggestions_page(message.chat.id, offset=0)
            return
        if data.startswith("admin:suggestions:page:"):
            await self._show_admin_suggestions_page(
                message.chat.id,
                offset=int(data.rsplit(":", 1)[1]),
            )
            return

        await message.answer(texts.ADMIN_STATE_MISSING_TEXT, reply_markup=self._admin_root_markup())

    async def _handle_admin_broadcast_text(self, message: Message, state: FSMContext) -> None:
        if not self._is_admin(message.chat.id):
            return
        if not self._supports_broadcast_message(message):
            await message.answer(texts.ADMIN_BROADCAST_UNSUPPORTED_TEXT)
            return
        if message.media_group_id:
            self._queue_admin_broadcast_media_group(message, state)
            return
        broadcast_text = self._extract_broadcast_text(message)
        await state.update_data(admin_broadcast_text=broadcast_text)
        await state.update_data(
            admin_broadcast_source_chat_id=message.chat.id,
            admin_broadcast_source_message_ids=[message.message_id],
            admin_broadcast_content_label=self._describe_broadcast_content(message),
        )
        await message.answer(
            texts.ADMIN_BROADCAST_AUDIENCE_PROMPT,
            reply_markup=self._broadcast_audience_markup(),
        )

    async def _handle_admin_broadcast_days(self, message: Message, state: FSMContext) -> None:
        if not self._is_admin(message.chat.id):
            return
        raw_days = (message.text or "").strip()
        if not raw_days.isdigit() or int(raw_days) <= 0:
            await message.answer(texts.ADMIN_BROADCAST_DAYS_ERROR_TEXT)
            return
        days = int(raw_days)
        recipients = await self._collect_broadcast_recipients(BroadcastAudience.ACTIVE_DAYS, days)
        if not recipients:
            await state.clear()
            await message.answer(
                texts.ADMIN_BROADCAST_NO_RECIPIENTS_TEXT,
                reply_markup=self._admin_root_markup(),
            )
            return
        await state.update_data(
            admin_broadcast_audience=BroadcastAudience.ACTIVE_DAYS.value,
            admin_broadcast_days=days,
            admin_broadcast_recipient_count=len(recipients),
        )
        await state.set_state(AdminBroadcastFlow.confirm)
        data = await state.get_data()
        await self._copy_broadcast_preview_from_state(message.chat.id, data)
        await message.answer(
            self._build_broadcast_confirmation(
                BroadcastAudience.ACTIVE_DAYS,
                days,
                len(recipients),
                str(data.get("admin_broadcast_content_label") or "сообщение"),
            ),
            reply_markup=self._broadcast_confirm_markup(),
        )

    def _queue_admin_broadcast_media_group(self, message: Message, state: FSMContext) -> None:
        """Поставить альбом администратора в очередь на сборку и обработку.

        Args:
            message: Очередное сообщение из media group.
            state: Контекст FSM админской рассылки.
        """
        media_group_id = message.media_group_id
        if media_group_id is None:
            return
        key = (message.chat.id, media_group_id)
        items = self._pending_broadcast_media_groups.setdefault(key, [])
        items.append(message)

        existing_task = self._pending_broadcast_media_group_tasks.get(key)
        if existing_task is not None:
            existing_task.cancel()

        task = asyncio.create_task(
            self._finalize_admin_broadcast_media_group(
                chat_id=message.chat.id,
                media_group_id=media_group_id,
                state=state,
            )
        )
        task.add_done_callback(
            lambda finished_task: self._log_pending_task_exception(finished_task)
        )
        self._pending_broadcast_media_group_tasks[key] = task

    async def _finalize_admin_broadcast_media_group(
        self,
        chat_id: int,
        media_group_id: str,
        state: FSMContext,
    ) -> None:
        """Дождаться завершения альбома и сохранить его как одну рассылку.

        Args:
            chat_id: Chat ID администратора.
            media_group_id: Идентификатор Telegram media group.
            state: Контекст FSM админской рассылки.

        Raises:
            asyncio.CancelledError: Если ожидание альбома было прервано новой задачей.
        """
        key = (chat_id, media_group_id)
        try:
            await asyncio.sleep(0.7)
            messages = self._pending_broadcast_media_groups.pop(key, [])
            if not messages:
                return
            ordered_messages = sorted(messages, key=lambda item: item.message_id)
            source_message_ids = [item.message_id for item in ordered_messages]
            broadcast_text = next(
                (
                    self._extract_broadcast_text(item)
                    for item in ordered_messages
                    if self._extract_broadcast_text(item)
                ),
                "",
            )
            content_label = self._describe_broadcast_media_group(ordered_messages)
            await state.update_data(
                admin_broadcast_text=broadcast_text,
                admin_broadcast_source_chat_id=chat_id,
                admin_broadcast_source_message_ids=source_message_ids,
                admin_broadcast_content_label=content_label,
            )
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_BROADCAST_AUDIENCE_PROMPT,
                reply_markup=self._broadcast_audience_markup(),
            )
        except asyncio.CancelledError:
            raise
        finally:
            self._pending_broadcast_media_group_tasks.pop(key, None)

    async def _handle_admin_entry_input(self, message: Message, state: FSMContext) -> None:
        if not self._is_admin(message.chat.id):
            return
        data = await state.get_data()
        input_mode = data.get("admin_entries_input_mode")
        value = (message.text or "").strip()
        if input_mode == "word_filter":
            await state.update_data(admin_entries_word_filter=value or None)
            await self._show_admin_entries_page(message.chat.id, state, offset=0)
            return
        if input_mode == "author_filter":
            await state.update_data(admin_entries_author_filter=value or None)
            await self._show_admin_entries_page(message.chat.id, state, offset=0)
            return
        if input_mode == "open":
            if not value.isdigit():
                await message.answer(texts.ADMIN_ENTRY_ID_ERROR_TEXT)
                return
            await self._show_admin_entry_details(message.chat.id, int(value))
            return
        entry_id = data.get("admin_edit_entry_id")
        field_name = data.get("admin_edit_field")
        if entry_id is None or field_name is None:
            await state.clear()
            await message.answer(
                texts.ADMIN_STATE_MISSING_TEXT,
                reply_markup=self._admin_root_markup(),
            )
            return
        updated = await asyncio.to_thread(
            self._user_repository.update_user_entry_field,
            int(entry_id),
            str(field_name),
            value,
        )
        await state.clear()
        await message.answer(
            texts.ADMIN_ENTRIES_EDIT_SUCCESS_TEXT if updated else texts.ADMIN_ENTRIES_NOT_FOUND_TEXT
        )
        if updated:
            await self._show_admin_entry_details(message.chat.id, int(entry_id))

    async def _handle_admin_comment_input(self, message: Message, state: FSMContext) -> None:
        if not self._is_admin(message.chat.id):
            return
        data = await state.get_data()
        input_mode = data.get("admin_comments_input_mode")
        value = (message.text or "").strip()
        if input_mode == "entry_filter":
            await state.update_data(admin_comments_entry_filter=value or None)
            await self._show_admin_comments_page(message.chat.id, state, offset=0)
            return
        if input_mode == "author_filter":
            await state.update_data(admin_comments_author_filter=value or None)
            await self._show_admin_comments_page(message.chat.id, state, offset=0)
            return
        if input_mode == "delete":
            if not value.isdigit():
                await message.answer(texts.ADMIN_COMMENT_ID_ERROR_TEXT)
                return
            deleted = await asyncio.to_thread(self._main_repository.delete_comment, int(value))
            await state.clear()
            await message.answer(
                texts.ADMIN_COMMENTS_DELETE_SUCCESS_TEXT
                if deleted
                else texts.ADMIN_COMMENTS_NOT_FOUND_TEXT
            )
            await self._show_admin_comments_page(message.chat.id, state, offset=0)

    async def _handle_mode_command(self, message: Message) -> None:
        await self._track_message(message, "/mode")
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=texts.MODE_LITE_BUTTON_TEXT,
                        callback_data="mode:lite",
                    ),
                    InlineKeyboardButton(
                        text=texts.MODE_COMPLEX_BUTTON_TEXT,
                        callback_data="mode:complex",
                    ),
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
            await self._notify_admin(
                f"Пользователь {self._format_user_actor(actor)} переключил режим на {mode.value}"
            )
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

        actor = self._extract_actor(message)
        search_context = self._build_search_error_context(actor, query)
        logger.info("Incoming search: %s", search_context)
        try:
            await asyncio.to_thread(self._db_repository.ensure_user, actor)
            mode = await asyncio.to_thread(self._db_repository.get_user_mode, message.chat.id)
            await self._notify_admin(
                f'Пользователь {self._format_actor(message)} ищет "{query}" (режим: {mode.value})'
            )
            search_result = await asyncio.to_thread(
                self._search_service.search_with_diagnostics,
                query,
                mode,
            )
            entries = search_result.entries
            if search_result.fallback_used:
                await self._notify_admin(
                    self._build_search_fallback_notification(actor, query, search_result)
                )
            await asyncio.to_thread(
                self._db_repository.log_search_query,
                query,
                actor.chat_id,
                bool(entries),
            )
        except Exception as exc:  # pragma: no cover
            await self._handle_failure(message.chat.id, exc, context=search_context)
            return

        if not entries:
            await self._notify_admin(
                f'По запросу "{query}" для пользователя {self._format_actor(message)} '
                f"ничего не найдено (режим: {mode.value})"
            )
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
        action_context = self._build_action_error_context(actor, action)
        logger.info("Incoming action: %s", action_context)
        try:
            await asyncio.to_thread(self._db_repository.ensure_user, actor)
            await asyncio.to_thread(self._db_repository.log_action, action, actor.chat_id)
            if action.startswith("/"):
                await self._notify_admin(
                    f"Пользователь {self._format_actor(message)} использовал команду {action}"
                )
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to track message (%s)", action_context)
            await self._notify_admin(f"Ошибка логирования: {action_context}\n{exc}")

    async def _handle_failure(
        self,
        chat_id: int,
        exc: Exception,
        user_message: str = texts.GENERIC_ERROR_TEXT,
        context: str | None = None,
    ) -> None:
        if context:
            logger.exception("Bot handler failed (%s)", context)
            await self._notify_admin(f"Ошибка: {context}\n{exc}")
        else:
            logger.exception("Bot handler failed")
            await self._notify_admin(f"Ошибка: {exc}")
        await self._bot.send_message(chat_id, user_message)

    async def _notify_admin(self, text: str) -> None:
        if self._config.logs_chat_id is None:
            return
        try:
            await self._bot.send_message(self._config.logs_chat_id, text)
        except Exception:  # pragma: no cover
            logger.exception("Failed to notify admin")

    @staticmethod
    def _log_pending_task_exception(task: asyncio.Task[None]) -> None:
        """Залогировать исключение фоновой задачи, если оно произошло.

        Args:
            task: Завершённая фоновая задача.
        """
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:  # pragma: no cover
            logger.exception("Background admin task failed")

    async def _handle_broadcast_audience_callback(
        self,
        message: Message,
        state: FSMContext,
        data: str,
    ) -> None:
        audience = BroadcastAudience(data.rsplit(":", 1)[1])
        if audience == BroadcastAudience.ACTIVE_DAYS:
            await state.set_state(AdminBroadcastFlow.days)
            await message.answer(texts.ADMIN_BROADCAST_DAYS_PROMPT)
            return
        recipients = await self._collect_broadcast_recipients(audience, None)
        if not recipients:
            await state.clear()
            await message.answer(
                texts.ADMIN_BROADCAST_NO_RECIPIENTS_TEXT,
                reply_markup=self._admin_root_markup(),
            )
            return
        await state.update_data(admin_broadcast_audience=audience.value, admin_broadcast_days=None)
        await state.update_data(admin_broadcast_recipient_count=len(recipients))
        await state.set_state(AdminBroadcastFlow.confirm)
        state_data = await state.get_data()
        await self._copy_broadcast_preview_from_state(message.chat.id, state_data)
        await message.answer(
            self._build_broadcast_confirmation(
                audience,
                None,
                len(recipients),
                str(state_data.get("admin_broadcast_content_label") or "сообщение"),
            ),
            reply_markup=self._broadcast_confirm_markup(),
        )

    async def _send_broadcast(self, chat_id: int, state: FSMContext) -> None:
        data = await state.get_data()
        broadcast_text = str(data.get("admin_broadcast_text") or "").strip()
        source_chat_id = data.get("admin_broadcast_source_chat_id")
        source_message_ids = self._normalize_source_message_ids(
            data.get("admin_broadcast_source_message_ids")
        )
        audience_raw = data.get("admin_broadcast_audience")
        if audience_raw is None or source_chat_id is None or not source_message_ids:
            await state.clear()
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_STATE_MISSING_TEXT,
                reply_markup=self._admin_root_markup(),
            )
            return

        audience = BroadcastAudience(str(audience_raw))
        days = int(data.get("admin_broadcast_days") or 0) or None
        recipients = await self._collect_broadcast_recipients(audience, days)
        if not recipients:
            await state.clear()
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_BROADCAST_NO_RECIPIENTS_TEXT,
                reply_markup=self._admin_root_markup(),
            )
            return

        broadcast_id = await asyncio.to_thread(
            self._db_repository.create_broadcast,
            chat_id,
            audience,
            days,
            int(source_chat_id),
            source_message_ids,
            broadcast_text,
            str(data.get("admin_broadcast_content_label") or "сообщение"),
            recipients,
        )
        await state.clear()
        await self._bot.send_message(chat_id, texts.ADMIN_BROADCAST_STARTED_TEXT)
        progress = await self._run_broadcast(broadcast_id)
        await self._bot.send_message(
            chat_id,
            texts.ADMIN_BROADCAST_SENT_TEXT,
            reply_markup=self._admin_root_markup(),
        )
        await self._bot.send_message(
            chat_id,
            self._build_broadcast_report(progress),
            reply_markup=self._broadcast_report_markup(progress),
        )

    async def _retry_broadcast(self, chat_id: int, broadcast_id: int) -> None:
        """Повторно отправить рассылку только тем, кому она не дошла.

        Args:
            chat_id: Chat ID администратора, запросившего повторную отправку.
            broadcast_id: Идентификатор уже созданной рассылки.
        """
        broadcast = await asyncio.to_thread(self._db_repository.fetch_broadcast, broadcast_id)
        if broadcast is None:
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_BROADCAST_NOT_FOUND_TEXT,
                reply_markup=self._admin_root_markup(),
            )
            return

        retry_targets = await asyncio.to_thread(
            self._db_repository.fetch_broadcast_delivery_targets,
            broadcast_id,
            (
                BroadcastDeliveryStatus.PENDING,
                BroadcastDeliveryStatus.RETRY,
                BroadcastDeliveryStatus.FAILED,
            ),
        )
        if not retry_targets:
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_BROADCAST_NOTHING_TO_RETRY_TEXT,
                reply_markup=self._broadcast_report_markup(
                    await asyncio.to_thread(self._db_repository.finalize_broadcast, broadcast_id)
                ),
            )
            return

        await self._bot.send_message(chat_id, texts.ADMIN_BROADCAST_STARTED_TEXT)
        progress = await self._run_broadcast(broadcast_id)
        await self._bot.send_message(
            chat_id,
            self._build_broadcast_report(progress),
            reply_markup=self._broadcast_report_markup(progress),
        )

    async def _run_broadcast(self, broadcast_id: int) -> BroadcastProgress:
        """Выполнить отправку сохранённой рассылки и сохранить статусы доставки.

        Args:
            broadcast_id: Идентификатор сохранённой рассылки.

        Returns:
            Финальная агрегированная сводка по рассылке.

        Raises:
            RuntimeError: Если запись рассылки не найдена.
        """
        broadcast = await asyncio.to_thread(self._db_repository.fetch_broadcast, broadcast_id)
        if broadcast is None:
            raise RuntimeError(f"Рассылка #{broadcast_id} не найдена")

        await asyncio.to_thread(self._db_repository.mark_broadcast_running, broadcast_id)
        targets = await asyncio.to_thread(
            self._db_repository.fetch_broadcast_delivery_targets,
            broadcast_id,
            (
                BroadcastDeliveryStatus.PENDING,
                BroadcastDeliveryStatus.RETRY,
                BroadcastDeliveryStatus.FAILED,
            ),
        )

        for target in targets:
            try:
                telegram_message_id = await self._deliver_broadcast_message(
                    recipient_chat_id=target.chat_id,
                    source_chat_id=broadcast.source_chat_id,
                    source_message_ids=broadcast.source_message_ids,
                    fallback_text=broadcast.text_preview,
                )
                await asyncio.to_thread(
                    self._db_repository.mark_broadcast_delivery,
                    target.delivery_id,
                    BroadcastDeliveryStatus.SENT,
                    telegram_message_id=telegram_message_id,
                )
            except TelegramForbiddenError as exc:
                await asyncio.to_thread(
                    self._db_repository.mark_broadcast_delivery,
                    target.delivery_id,
                    BroadcastDeliveryStatus.BLOCKED,
                    error_text=str(exc),
                )
            except TelegramRetryAfter as exc:
                await asyncio.sleep(float(exc.retry_after))
                try:
                    telegram_message_id = await self._deliver_broadcast_message(
                        recipient_chat_id=target.chat_id,
                        source_chat_id=broadcast.source_chat_id,
                        source_message_ids=broadcast.source_message_ids,
                        fallback_text=broadcast.text_preview,
                    )
                    await asyncio.to_thread(
                        self._db_repository.mark_broadcast_delivery,
                        target.delivery_id,
                        BroadcastDeliveryStatus.SENT,
                        telegram_message_id=telegram_message_id,
                    )
                except TelegramForbiddenError as retry_exc:
                    await asyncio.to_thread(
                        self._db_repository.mark_broadcast_delivery,
                        target.delivery_id,
                        BroadcastDeliveryStatus.BLOCKED,
                        error_text=str(retry_exc),
                    )
                except TelegramBadRequest as retry_exc:
                    await asyncio.to_thread(
                        self._db_repository.mark_broadcast_delivery,
                        target.delivery_id,
                        BroadcastDeliveryStatus.FAILED,
                        error_text=str(retry_exc),
                    )
                except TelegramRetryAfter as retry_exc:
                    await asyncio.to_thread(
                        self._db_repository.mark_broadcast_delivery,
                        target.delivery_id,
                        BroadcastDeliveryStatus.RETRY,
                        error_text=str(retry_exc),
                    )
                except Exception as retry_exc:  # pragma: no cover
                    logger.exception("Broadcast retry delivery failed")
                    await asyncio.to_thread(
                        self._db_repository.mark_broadcast_delivery,
                        target.delivery_id,
                        BroadcastDeliveryStatus.RETRY,
                        error_text=str(retry_exc),
                    )
            except TelegramBadRequest as exc:
                await asyncio.to_thread(
                    self._db_repository.mark_broadcast_delivery,
                    target.delivery_id,
                    BroadcastDeliveryStatus.FAILED,
                    error_text=str(exc),
                )
            except Exception as exc:  # pragma: no cover
                logger.exception("Broadcast delivery failed")
                await asyncio.to_thread(
                    self._db_repository.mark_broadcast_delivery,
                    target.delivery_id,
                    BroadcastDeliveryStatus.RETRY,
                    error_text=str(exc),
                )
            await asyncio.sleep(0.1)

        return await asyncio.to_thread(self._db_repository.finalize_broadcast, broadcast_id)

    async def _collect_broadcast_recipients(
        self,
        audience: BroadcastAudience,
        days: int | None,
    ) -> list[BroadcastRecipient]:
        if audience == BroadcastAudience.ALL:
            return await asyncio.to_thread(self._db_repository.fetch_broadcast_recipients_all)
        if audience == BroadcastAudience.WITH_ACTIONS:
            return await asyncio.to_thread(
                self._db_repository.fetch_broadcast_recipients_with_actions
            )
        return await asyncio.to_thread(
            self._db_repository.fetch_broadcast_recipients_active,
            days or 1,
        )

    async def _show_admin_stats(self, chat_id: int) -> None:
        stats = await asyncio.to_thread(self._db_repository.fetch_admin_stats)
        await self._bot.send_message(
            chat_id,
            self._build_stats_summary(
                total_users=stats.total_users,
                active_users_day=stats.active_users_day,
                active_users_week=stats.active_users_week,
                active_users_month=stats.active_users_month,
                new_users_day=stats.new_users_day,
                new_users_week=stats.new_users_week,
                new_users_month=stats.new_users_month,
                total_searches=stats.total_searches,
                top_queries=stats.top_queries,
                failed_queries=stats.failed_queries,
                user_entries=stats.user_entries_count,
                comments=stats.comments_count,
                suggestions=stats.suggestions_count,
            ),
            reply_markup=self._admin_root_markup(),
        )

    async def _show_scoreboard(
        self,
        chat_id: int,
        period: ScorePeriod = ScorePeriod.ALL_TIME,
    ) -> None:
        scoreboard = await asyncio.to_thread(
            self._db_repository.fetch_scoreboard,
            chat_id,
            period,
        )
        await self._bot.send_message(
            chat_id,
            self._build_scoreboard_text(scoreboard),
            reply_markup=self._scoreboard_markup(period),
        )

    async def _show_admin_entries_page(
        self,
        chat_id: int,
        state: FSMContext,
        offset: int,
    ) -> None:
        await state.set_state(AdminEntriesFlow.browse)
        state_data = await state.get_data()
        records = await asyncio.to_thread(
            self._user_repository.list_user_entries,
            self._ADMIN_PAGE_SIZE,
            offset,
            state_data.get("admin_entries_word_filter"),
            state_data.get("admin_entries_author_filter"),
        )
        await state.update_data(admin_entries_offset=offset, admin_entries_input_mode=None)
        if not records:
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_ENTRIES_EMPTY_TEXT,
                reply_markup=self._admin_entries_markup(offset, has_next=False),
            )
            return

        cards = [
            self._build_user_entry_card(
                entry=record.entry,
                added_at=self._format_datetime(record.created_at),
                author=record.author,
                entry_id=record.entry_id,
                compact=True,
            )
            for record in records
        ]
        filters_line = self._build_admin_filters_line(
            state_data.get("admin_entries_word_filter"),
            state_data.get("admin_entries_author_filter"),
        )
        await self._bot.send_message(
            chat_id,
            f"{texts.ADMIN_ENTRIES_LIST_TITLE}\n{filters_line}\n\n" + "\n\n".join(cards),
            reply_markup=self._admin_entries_markup(
                offset=offset,
                has_next=len(records) == self._ADMIN_PAGE_SIZE,
            ),
        )

    async def _show_admin_entry_details(self, chat_id: int, entry_id: int) -> None:
        record = await asyncio.to_thread(self._user_repository.get_user_entry, entry_id)
        if record is None:
            await self._bot.send_message(chat_id, texts.ADMIN_ENTRIES_NOT_FOUND_TEXT)
            return
        await self._bot.send_message(
            chat_id,
            self._build_user_entry_card(
                entry=record.entry,
                added_at=self._format_datetime(record.created_at),
                author=record.author,
                entry_id=record.entry_id,
            ),
            reply_markup=self._admin_entry_details_markup(record.entry_id),
        )

    async def _show_admin_comments_page(
        self,
        chat_id: int,
        state: FSMContext,
        offset: int,
    ) -> None:
        await state.set_state(AdminCommentsFlow.browse)
        state_data = await state.get_data()
        records = await asyncio.to_thread(
            self._main_repository.list_comments,
            self._ADMIN_PAGE_SIZE,
            offset,
            state_data.get("admin_comments_entry_filter"),
            state_data.get("admin_comments_author_filter"),
        )
        await state.update_data(admin_comments_offset=offset, admin_comments_input_mode=None)
        if not records:
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_COMMENTS_EMPTY_TEXT,
                reply_markup=self._admin_comments_markup(offset, has_next=False),
            )
            return

        cards = [
            self._build_comment_card(
                entry_title=record.entry_title,
                comment_text=record.comment_text,
                author=record.author,
                created_at=self._format_datetime(record.created_at),
                comment_id=record.comment_id,
                entry_id=record.entry_id,
            )
            for record in records
        ]
        filters_line = self._build_admin_filters_line(
            state_data.get("admin_comments_entry_filter"),
            state_data.get("admin_comments_author_filter"),
        )
        await self._bot.send_message(
            chat_id,
            f"{texts.ADMIN_COMMENTS_LIST_TITLE}\n{filters_line}\n\n" + "\n\n".join(cards),
            reply_markup=self._admin_comments_markup(
                offset=offset,
                has_next=len(records) == self._ADMIN_PAGE_SIZE,
            ),
        )

    async def _show_admin_suggestions_page(self, chat_id: int, offset: int) -> None:
        suggestions = await asyncio.to_thread(
            self._db_repository.fetch_suggestions,
            self._ADMIN_PAGE_SIZE,
            offset,
        )
        if not suggestions:
            await self._bot.send_message(
                chat_id,
                texts.ADMIN_SUGGESTIONS_EMPTY_TEXT,
                reply_markup=self._admin_suggestions_markup(offset, has_next=False),
            )
            return
        await self._bot.send_message(
            chat_id,
            f"{texts.ADMIN_SUGGESTIONS_LIST_TITLE}\n\n"
            + "\n\n".join(self._build_suggestion_card(item) for item in suggestions),
            reply_markup=self._admin_suggestions_markup(
                offset=offset,
                has_next=len(suggestions) == self._ADMIN_PAGE_SIZE,
            ),
        )

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
        return chat_id in self._config.admins_chat_ids

    @staticmethod
    def _format_actor(message: Message) -> str:
        from_user = message.from_user
        if from_user is None:
            return str(message.chat.id)
        username = f"@{from_user.username}" if from_user.username else str(message.chat.id)
        return f'{username} "{from_user.first_name}"'

    @staticmethod
    def _format_user_actor(user: TelegramUser) -> str:
        """Сформатировать доменную модель пользователя для логов.

        Args:
            user: Пользователь Telegram.

        Returns:
            Короткая строка для сообщений в чат логов.
        """
        username = f"@{user.username}" if user.username else str(user.chat_id)
        return f'{username} "{user.first_name}"'

    @staticmethod
    def _format_actor_debug(user: TelegramUser) -> str:
        username = f"@{user.username}" if user.username else "-"
        full_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
        name = full_name or user.first_name or "-"
        return f'chat_id={user.chat_id}, username={username}, name="{name}"'

    @classmethod
    def _build_search_error_context(cls, actor: TelegramUser, query: str) -> str:
        safe_query = " ".join(query.split())
        return f'{cls._format_actor_debug(actor)}, query="{safe_query}"'

    @classmethod
    def _build_search_fallback_notification(
        cls,
        actor: TelegramUser,
        query: str,
        search_result: SearchResult,
    ) -> str:
        safe_query = " ".join(query.split())
        provider = search_result.fallback_provider or "unknown"
        reason = cls._truncate_text(search_result.fallback_reason or "-", 350)
        return (
            "RAG fallback: complex -> lite\n"
            f'User: {cls._format_actor_debug(actor)}\n'
            f'Query: "{safe_query}"\n'
            f"Provider: {provider}\n"
            f"Reason: {reason}"
        )

    @classmethod
    def _build_action_error_context(cls, actor: TelegramUser, action: str) -> str:
        safe_action = " ".join(action.split())
        return f'{cls._format_actor_debug(actor)}, action="{safe_action}"'

    def _admin_root_markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Рассылка", callback_data="admin:broadcast"),
                    InlineKeyboardButton(text="Статьи", callback_data="admin:entries"),
                ],
                [
                    InlineKeyboardButton(text="Комментарии", callback_data="admin:comments"),
                    InlineKeyboardButton(text="Статистика", callback_data="admin:stats"),
                ],
                [InlineKeyboardButton(text="Предложения", callback_data="admin:suggestions")],
            ]
        )

    @staticmethod
    def _scoreboard_markup(period: ScorePeriod) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=DictionaryBotHandlers._score_period_button_text(
                            ScorePeriod.ALL_TIME,
                            period,
                        ),
                        callback_data="score:period:all",
                    ),
                    InlineKeyboardButton(
                        text=DictionaryBotHandlers._score_period_button_text(
                            ScorePeriod.MONTH,
                            period,
                        ),
                        callback_data="score:period:month",
                    ),
                    InlineKeyboardButton(
                        text=DictionaryBotHandlers._score_period_button_text(
                            ScorePeriod.WEEK,
                            period,
                        ),
                        callback_data="score:period:week",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=texts.SCORE_BUTTON_TELEGRAM_TEXT,
                        callback_data=f"score:telegram:{period.value}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=texts.SCORE_BUTTON_CUSTOM_TEXT,
                        callback_data=f"score:custom:{period.value}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=texts.SCORE_BUTTON_ANONYMOUS_TEXT,
                        callback_data=f"score:anonymous:{period.value}",
                    ),
                    InlineKeyboardButton(
                        text=texts.SCORE_BUTTON_REFRESH_TEXT,
                        callback_data=f"score:refresh:{period.value}",
                    ),
                ],
            ]
        )

    @staticmethod
    def _suggest_cancel_markup() -> InlineKeyboardMarkup:
        """Собрать клавиатуру отмены для сценария `/suggest`.

        Returns:
            Inline-клавиатура с единственной кнопкой отмены.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=texts.SUGGEST_CANCEL_BUTTON_TEXT,
                        callback_data="suggest:cancel",
                    )
                ]
            ]
        )

    def _broadcast_audience_markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Всем", callback_data="admin:broadcast:audience:all"),
                    InlineKeyboardButton(
                        text="Активным за N дней",
                        callback_data="admin:broadcast:audience:active_days",
                    ),
                ],
                [InlineKeyboardButton(text="Отмена", callback_data="admin:broadcast:cancel")],
            ]
        )

    def _broadcast_confirm_markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Отправить", callback_data="admin:broadcast:send"),
                    InlineKeyboardButton(
                        text="Изменить сообщение",
                        callback_data="admin:broadcast:edit",
                    ),
                ],
                [InlineKeyboardButton(text="Отмена", callback_data="admin:broadcast:cancel")],
            ]
        )

    @staticmethod
    def _broadcast_report_markup(progress: BroadcastProgress) -> InlineKeyboardMarkup:
        """Собрать клавиатуру для итогового отчёта по рассылке.

        Args:
            progress: Финальная сводка по результатам рассылки.

        Returns:
            Клавиатура с повторной отправкой и возвратом в меню.
        """
        keyboard: list[list[InlineKeyboardButton]] = []
        retryable_count = progress.retry_count + progress.failed_count + progress.pending_count
        if retryable_count > 0:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        text="Повторить недоставленным",
                        callback_data=f"admin:broadcast:retry:{progress.broadcast_id}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton(text="В меню", callback_data="admin:root")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _admin_entries_markup(self, offset: int, has_next: bool) -> InlineKeyboardMarkup:
        keyboard: list[list[InlineKeyboardButton]] = []
        pagination = self._build_pagination_row("admin:entries:page", offset, has_next)
        if pagination:
            keyboard.append(pagination)
        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        text="Фильтр по слову",
                        callback_data="admin:entries:filter:word",
                    ),
                    InlineKeyboardButton(
                        text="Фильтр по автору",
                        callback_data="admin:entries:filter:author",
                    ),
                ],
                [
                    InlineKeyboardButton(text="Открыть по ID", callback_data="admin:entries:open"),
                    InlineKeyboardButton(
                        text="Сбросить фильтры",
                        callback_data="admin:entries:filters:clear",
                    ),
                ],
                [InlineKeyboardButton(text="В меню", callback_data="admin:root")],
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _admin_entry_details_markup(self, entry_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Редактировать слово",
                        callback_data=f"admin:entries:edit:{entry_id}:word",
                    ),
                    InlineKeyboardButton(
                        text="Редактировать перевод",
                        callback_data=f"admin:entries:edit:{entry_id}:translation",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Редактировать фразы",
                        callback_data=f"admin:entries:edit:{entry_id}:phrases_raw",
                    ),
                    InlineKeyboardButton(
                        text="Редактировать доп.инфо",
                        callback_data=f"admin:entries:edit:{entry_id}:supporting_raw",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Удалить",
                        callback_data=f"admin:entries:delete:{entry_id}",
                    ),
                    InlineKeyboardButton(text="К списку", callback_data="admin:entries"),
                ],
                [InlineKeyboardButton(text="В меню", callback_data="admin:root")],
            ]
        )

    def _confirm_delete_entry_markup(self, entry_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Подтвердить удаление",
                        callback_data=f"admin:entries:delete_confirm:{entry_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Назад",
                        callback_data=f"admin:entries:open:{entry_id}",
                    ),
                    InlineKeyboardButton(text="В меню", callback_data="admin:root"),
                ],
            ]
        )

    def _admin_comments_markup(self, offset: int, has_next: bool) -> InlineKeyboardMarkup:
        keyboard: list[list[InlineKeyboardButton]] = []
        pagination = self._build_pagination_row("admin:comments:page", offset, has_next)
        if pagination:
            keyboard.append(pagination)
        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        text="Фильтр по статье",
                        callback_data="admin:comments:filter:entry",
                    ),
                    InlineKeyboardButton(
                        text="Фильтр по автору",
                        callback_data="admin:comments:filter:author",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Удалить по ID",
                        callback_data="admin:comments:delete",
                    ),
                    InlineKeyboardButton(
                        text="Сбросить фильтры",
                        callback_data="admin:comments:filters:clear",
                    ),
                ],
                [InlineKeyboardButton(text="В меню", callback_data="admin:root")],
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _admin_suggestions_markup(self, offset: int, has_next: bool) -> InlineKeyboardMarkup:
        keyboard: list[list[InlineKeyboardButton]] = []
        pagination = self._build_pagination_row("admin:suggestions:page", offset, has_next)
        if pagination:
            keyboard.append(pagination)
        keyboard.append([InlineKeyboardButton(text="В меню", callback_data="admin:root")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _build_pagination_row(
        self,
        prefix: str,
        offset: int,
        has_next: bool,
    ) -> list[InlineKeyboardButton]:
        row: list[InlineKeyboardButton] = []
        if offset > 0:
            row.append(
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=f"{prefix}:{max(offset - self._ADMIN_PAGE_SIZE, 0)}",
                )
            )
        if has_next:
            row.append(
                InlineKeyboardButton(
                    text="Дальше",
                    callback_data=f"{prefix}:{offset + self._ADMIN_PAGE_SIZE}",
                )
            )
        return row

    def _edit_prompt_for_field(self, field_name: str) -> str:
        prompts = {
            "word": texts.ADMIN_ENTRY_EDIT_WORD_PROMPT,
            "translation": texts.ADMIN_ENTRY_EDIT_TRANSLATION_PROMPT,
            "phrases_raw": texts.ADMIN_ENTRY_EDIT_PHRASES_PROMPT,
            "supporting_raw": texts.ADMIN_ENTRY_EDIT_SUPPORTING_PROMPT,
        }
        return prompts.get(field_name, texts.ADMIN_STATE_MISSING_TEXT)

    @staticmethod
    def _build_broadcast_preview(text_value: str, content_label: str) -> str:
        text_block = text_value or "Без подписи"
        return (
            f"{texts.ADMIN_BROADCAST_PREVIEW_TITLE}\n\n"
            f"Тип сообщения: {content_label}\n\n"
            f"{text_block}\n\n"
            f"{texts.ADMIN_BROADCAST_AUDIENCE_PROMPT}"
        )

    @staticmethod
    def _build_broadcast_confirmation(
        audience: BroadcastAudience,
        days: int | None,
        recipients_count: int,
        content_label: str,
    ) -> str:
        audience_label = {
            BroadcastAudience.ALL: "все пользователи бота",
            BroadcastAudience.ACTIVE_DAYS: f"активные за {days} дн.",
            BroadcastAudience.WITH_ACTIONS: "все, кто писал боту",
        }[audience]
        return (
            f"{texts.ADMIN_BROADCAST_CONFIRM_TITLE}\n\n"
            f"Аудитория: {audience_label}\n"
            f"Адресатов: {recipients_count}\n"
            f"Тип сообщения: {content_label}"
        )

    @staticmethod
    def _build_broadcast_report(progress: BroadcastProgress) -> str:
        return texts.ADMIN_BROADCAST_REPORT_TEXT.format(
            broadcast_id=progress.broadcast_id,
            total=progress.total_recipients,
            success=progress.sent_count,
            blocked=progress.blocked_count,
            retryable=progress.retry_count + progress.failed_count + progress.pending_count,
            errors=progress.failed_count,
        )

    @classmethod
    def _build_user_entry_card(
        cls,
        entry: DictionaryEntry,
        added_at: str,
        author: TelegramUser | None = None,
        entry_id: int | None = None,
        compact: bool = False,
    ) -> str:
        lines: list[str] = []
        if entry_id is not None:
            lines.append(f"#{entry_id} · {entry.title}")
        else:
            lines.append(entry.title)
        lines.append(f"👤 Автор: {cls._format_admin_user(author, entry)}")
        lines.append(f"🕓 Дата: {added_at}")
        if compact:
            return "\n".join(lines)
        lines.append("")
        lines.append(format_entry(entry))
        return "\n".join(lines).strip()

    @classmethod
    def _build_comment_card(
        cls,
        entry_title: str,
        comment_text: str,
        author: TelegramUser | None,
        created_at: str,
        comment_id: int | None = None,
        entry_id: int | None = None,
    ) -> str:
        lines: list[str] = []
        if comment_id is not None:
            lines.append(f"#{comment_id} · {entry_title}")
        else:
            lines.append(f"Статья: {entry_title}")
        if entry_id is not None:
            lines.append(f"ID статьи: {entry_id}")
        lines.append(f"👤 Автор: {cls._format_admin_user(author)}")
        lines.append(f"🕓 Дата: {created_at}")
        lines.append(f"💬 {DictionaryBotHandlers._truncate_text(comment_text, 180)}")
        return "\n".join(lines)

    @classmethod
    def _build_suggestion_card(cls, suggestion: AdminSuggestion) -> str:
        return (
            f"#{suggestion.suggestion_id}\n"
            f"👤 Автор: {cls._format_admin_user(suggestion.author)}\n"
            f"🕓 Дата: {cls._format_datetime(suggestion.created_at)}\n"
            f"Статус: {suggestion.status}\n\n"
            f"{suggestion.text}"
        )

    @staticmethod
    def _build_stats_summary(
        total_users: int,
        active_users_day: int,
        active_users_week: int,
        active_users_month: int,
        new_users_day: int,
        new_users_week: int,
        new_users_month: int,
        total_searches: int,
        top_queries: Any,
        failed_queries: Any,
        user_entries: int,
        comments: int,
        suggestions: int,
    ) -> str:
        top_queries_text = DictionaryBotHandlers._format_query_stats(top_queries)
        failed_queries_text = DictionaryBotHandlers._format_query_stats(failed_queries)
        failed_total = DictionaryBotHandlers._query_stats_total(failed_queries)
        return (
            f"{texts.ADMIN_STATS_TITLE}\n\n"
            f"👥 Пользователи: {total_users}\n"
            f"🆕 Новые за день / неделю / месяц: "
            f"{new_users_day} / {new_users_week} / {new_users_month}\n"
            f"🔥 Активные за день / неделю / месяц: "
            f"{active_users_day} / {active_users_week} / {active_users_month}\n\n"
            f"🔎 Всего поисков: {total_searches}\n"
            f"🏷 Топ запросов: {top_queries_text}\n"
            f"⚠️ Неудачных запросов: {failed_total}\n"
            f"🧩 Частые неудачные запросы: {failed_queries_text}\n\n"
            f"📝 Пользовательских статей: {user_entries}\n"
            f"💬 Комментариев: {comments}\n"
            f"💡 Предложений: {suggestions}"
        )

    @classmethod
    def _build_scoreboard_text(cls, scoreboard: ScoreBoard) -> str:
        sections = [
            cls._build_score_category(
                "📝 Статьи",
                scoreboard.user_entries,
                scoreboard.personal_user_entries,
            ),
            cls._build_score_category(
                "💬 Комментарии",
                scoreboard.comments,
                scoreboard.personal_comments,
            ),
            cls._build_score_category(
                "💡 Предложения",
                scoreboard.suggestions,
                scoreboard.personal_suggestions,
            ),
            cls._build_score_category(
                "🔎 Поиски",
                scoreboard.searches,
                scoreboard.personal_searches,
            ),
        ]
        period_line = f"Период: {cls._score_period_label(scoreboard.period)}"
        return texts.SCORE_INTRO_TEXT + "\n\n" + period_line + "\n\n" + "\n\n".join(sections)

    @staticmethod
    def _build_score_category(
        title: str,
        entries: tuple[ScoreEntry, ...],
        personal_entry: ScoreEntry | None,
    ) -> str:
        lines = [title]
        if not entries:
            lines.append(texts.SCORE_EMPTY_CATEGORY_TEXT)
        else:
            lines.extend(f"{entry.rank}. {entry.display_name} — {entry.value}" for entry in entries)
        if personal_entry is not None:
            lines.append(f"… {personal_entry.rank}. Вы — {personal_entry.value}")
        return "\n".join(lines)

    @staticmethod
    def _query_stats_total(value: Any) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, (tuple, list)):
            total = 0
            for item in value:
                if isinstance(item, tuple) and len(item) >= 2:
                    total += int(item[1])
            return total
        return 0

    @staticmethod
    def _format_query_stats(value: Any) -> str:
        if isinstance(value, int):
            return str(value)
        if not value:
            return texts.ADMIN_STATS_TOP_QUERIES_EMPTY_TEXT
        parts: list[str] = []
        for item in value:
            if isinstance(item, tuple) and len(item) >= 2:
                parts.append(f"{item[0]} ({item[1]})")
            else:
                parts.append(str(item))
        return ", ".join(parts)

    @staticmethod
    def _normalize_score_alias(raw_alias: str) -> str | None:
        if "\n" in raw_alias or "\r" in raw_alias:
            return None
        alias = " ".join(raw_alias.split())
        lowered_alias = alias.lower()
        if not 2 <= len(alias) <= 24:
            return None
        if any(forbidden in lowered_alias for forbidden in ("http", "https", "t.me")):
            return None
        if "/" in alias or "@" in alias:
            return None
        if re.fullmatch(r"[0-9A-Za-zА-Яа-яЁё _.-]+", alias) is None:
            return None
        return alias

    @staticmethod
    def _score_period_from_callback(callback_data: str) -> ScorePeriod:
        raw_period = callback_data.rsplit(":", 1)[-1]
        try:
            return ScorePeriod(raw_period)
        except ValueError:
            return ScorePeriod.ALL_TIME

    @staticmethod
    def _score_period_label(period: ScorePeriod) -> str:
        labels = {
            ScorePeriod.ALL_TIME: texts.SCORE_PERIOD_ALL_TEXT,
            ScorePeriod.MONTH: texts.SCORE_PERIOD_MONTH_TEXT,
            ScorePeriod.WEEK: texts.SCORE_PERIOD_WEEK_TEXT,
        }
        return labels[period]

    @classmethod
    def _score_period_button_text(
        cls,
        period: ScorePeriod,
        current_period: ScorePeriod,
    ) -> str:
        label = cls._score_period_label(period)
        if period == current_period:
            return f"✓ {label}"
        return label

    @staticmethod
    def _build_admin_filters_line(primary: object, secondary: object) -> str:
        parts: list[str] = []
        if primary:
            parts.append(f"слово/статья: {primary}")
        if secondary:
            parts.append(f"автор: {secondary}")
        return "Фильтры: " + "; ".join(parts) if parts else "Фильтры: не заданы"

    @staticmethod
    def _supports_broadcast_message(message: Message) -> bool:
        return bool(message.text or message.caption or message.photo or message.document)

    @staticmethod
    def _extract_broadcast_text(message: Message) -> str:
        return (message.text or message.caption or "").strip()

    @staticmethod
    def _describe_broadcast_content(message: Message) -> str:
        if message.photo:
            return "фото"
        if message.document:
            return "файл"
        return "текст"

    @classmethod
    def _describe_broadcast_media_group(cls, messages: list[Message]) -> str:
        """Сформировать описание типа контента для media group.

        Args:
            messages: Сообщения из одного Telegram-альбома.

        Returns:
            Короткое описание альбома для превью и подтверждения рассылки.
        """
        photo_count = sum(1 for item in messages if item.photo)
        document_count = sum(1 for item in messages if item.document)
        if photo_count:
            suffix = "изображение" if photo_count == 1 else "изображения"
            return f"альбом ({photo_count} {suffix})"
        if document_count:
            suffix = "файл" if document_count == 1 else "файла"
            return f"альбом ({document_count} {suffix})"
        return f"альбом ({len(messages)} элементов)"

    @staticmethod
    def _normalize_source_message_ids(value: object) -> list[int]:
        """Преобразовать данные состояния в список исходных message_id.

        Args:
            value: Значение из FSM state.

        Returns:
            Список идентификаторов сообщений без пустых значений.
        """
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [int(item) for item in value]
        return [int(str(value))]

    async def _copy_broadcast_preview_from_state(self, chat_id: int, data: dict[str, Any]) -> None:
        source_chat_id = data.get("admin_broadcast_source_chat_id")
        source_message_ids = self._normalize_source_message_ids(
            data.get("admin_broadcast_source_message_ids")
        )
        if source_chat_id is None or not source_message_ids:
            return
        await self._copy_broadcast_preview(
            chat_id=chat_id,
            source_chat_id=int(source_chat_id),
            source_message_ids=source_message_ids,
        )

    async def _copy_broadcast_preview(
        self,
        chat_id: int,
        source_chat_id: int,
        source_message_ids: list[int],
    ) -> None:
        try:
            if len(source_message_ids) > 1:
                await self._bot.copy_messages(
                    chat_id=chat_id,
                    from_chat_id=source_chat_id,
                    message_ids=source_message_ids,
                )
            else:
                await self._bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=source_chat_id,
                    message_id=source_message_ids[0],
                )
        except TelegramBadRequest:
            logger.exception("Failed to copy broadcast preview")

    async def _deliver_broadcast_message(
        self,
        recipient_chat_id: int,
        source_chat_id: int,
        source_message_ids: tuple[int, ...],
        fallback_text: str,
    ) -> int | None:
        """Отправить одно сообщение рассылки конкретному пользователю.

        Args:
            recipient_chat_id: Chat ID адресата.
            source_chat_id: Чат, из которого нужно скопировать исходное сообщение.
            source_message_ids: Идентификаторы исходных сообщений.
            fallback_text: Текст, который будет отправлен при неудачном `copy_message`.

        Returns:
            Идентификатор созданного сообщения Telegram, если его удалось определить.

        Raises:
            TelegramBadRequest: Если копирование не удалось и fallback-текст отсутствует.
        """
        try:
            if len(source_message_ids) > 1:
                results = await self._bot.copy_messages(
                    chat_id=recipient_chat_id,
                    from_chat_id=source_chat_id,
                    message_ids=list(source_message_ids),
                )
                if not results:
                    return None
                return int(results[0].message_id)
            result = await self._bot.copy_message(
                chat_id=recipient_chat_id,
                from_chat_id=source_chat_id,
                message_id=source_message_ids[0],
            )
            return int(result.message_id)
        except TelegramBadRequest:
            if len(source_message_ids) > 1 or not fallback_text:
                raise

        message = await self._bot.send_message(recipient_chat_id, fallback_text)
        return int(message.message_id)

    @staticmethod
    def _truncate_text(value: str, limit: int) -> str:
        clean = " ".join(value.split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 1].rstrip() + "…"

    @staticmethod
    def _format_datetime(value: datetime | str) -> str:
        if isinstance(value, str):
            return value
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _format_admin_user(
        user: TelegramUser | None,
        entry: DictionaryEntry | None = None,
    ) -> str:
        if user is not None:
            username = f"@{user.username}" if user.username else "-"
            full_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
            return f"{username} | {full_name or 'без имени'} | {user.chat_id}"
        if entry is not None:
            username = f"@{entry.contributor_username}" if entry.contributor_username else "-"
            full_name = " ".join(
                part for part in (entry.contributor_first_name, entry.contributor_last_name) if part
            ).strip()
            if full_name or username != "-":
                return f"{username} | {full_name or 'без имени'}"
        return "не указан"

    @staticmethod
    def _build_suggestion_notification(
        actor: TelegramUser,
        suggestion_text: str,
        suggestion_id: int | None = None,
    ) -> str:
        """Собрать уведомление администратору о новом предложении.

        Args:
            actor: Пользователь, отправивший предложение.
            suggestion_text: Текст идеи или замечания.
            suggestion_id: Необязательный идентификатор предложения.

        Returns:
            Готовое текстовое уведомление для администратора.
        """
        username = f"@{actor.username}" if actor.username else str(actor.chat_id)
        full_name = " ".join(part for part in (actor.first_name, actor.last_name) if part).strip()
        prefix = "Новое предложение"
        if suggestion_id is not None:
            prefix += f" #{suggestion_id}"
        return (
            f"{prefix} от "
            f'{username} "{full_name or actor.first_name}" (chat_id={actor.chat_id}):\n\n'
            f"{suggestion_text}"
        )

    @classmethod
    def _build_user_profile_summary(
        cls,
        profile: UserProfileStats,
        reference_dt: datetime | None = None,
    ) -> str:
        """Собрать личную сводку пользователя для команды `/me`.

        Args:
            profile: Сводка по пользователю из базы данных.
            reference_dt: Точка отсчета для расчета числа дней использования бота.

        Returns:
            Готовый текст профиля пользователя.
        """
        mode_label = "расширенный" if profile.mode == SearchMode.COMPLEX else "точный"
        return (
            f"{texts.ME_TITLE_TEXT}\n\n"
            f"🔎 Режим поиска: {mode_label}\n"
            f"📅 Вы с ботом: {cls._format_profile_since(profile.created_at, reference_dt)}\n\n"
            f"Поисков: {profile.searches_count}\n"
            f"Статей добавлено: {profile.user_entries_count}\n"
            f"Комментариев: {profile.comments_count}\n"
            f"Предложений: {profile.suggestions_count}\n\n"
            f"chat_id: {profile.user.chat_id}"
        )

    @classmethod
    def _format_profile_since(
        cls,
        created_at: datetime,
        reference_dt: datetime | None = None,
    ) -> str:
        """Сформатировать дату первого использования бота с числом дней.

        Args:
            created_at: Дата первого появления пользователя в боте.
            reference_dt: Точка отсчета для расчета числа дней.

        Returns:
            Строка формата `03.04.2026 (7 дней)`.
        """
        reference = reference_dt or datetime.now(created_at.tzinfo)
        days_count = max((reference.date() - created_at.date()).days, 0)
        return f"{created_at.strftime('%d.%m.%Y')} ({days_count} {cls._pluralize_days(days_count)})"

    @staticmethod
    def _pluralize_days(value: int) -> str:
        """Подобрать правильное склонение для количества дней.

        Args:
            value: Количество дней.

        Returns:
            Подходящая словоформа: `день`, `дня` или `дней`.
        """
        if value % 10 == 1 and value % 100 != 11:
            return "день"
        if value % 10 in (2, 3, 4) and value % 100 not in (12, 13, 14):
            return "дня"
        return "дней"
