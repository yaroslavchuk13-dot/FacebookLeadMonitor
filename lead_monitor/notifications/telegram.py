"""Telegram bot: delivers leads and alerts, answers /status /pause /resume.

Leads are delivered from the database (posts with notified_at IS NULL), so nothing is lost
when Telegram is unreachable, and messages are spaced to respect Telegram rate limits.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from lead_monitor.core.models import ExtensionAlert
from lead_monitor.core.state import MonitorState
from lead_monitor.filters.keywords import KeywordFile
from lead_monitor.notifications.formatting import (
    HELP_TEXT,
    format_alert,
    format_lead,
    format_status,
    lead_button_text,
)
from lead_monitor.storage.database import Database, StoredPost

log = logging.getLogger(__name__)

SEND_INTERVAL_SECONDS = 1.1  # Telegram: about 1 message per second per chat
DELIVERY_POLL_SECONDS = 30  # also retry pending leads periodically (e.g. after a network error)
NETWORK_ERROR_PAUSE_SECONDS = 30
SILENCE_ALERT_SECONDS = 10 * 60  # extension silent this long while monitoring -> alert
SILENCE_CHECK_SECONDS = 60


def _lead_markup(lead: dict[str, Any]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=lead_button_text(lead), url=lead["post_url"])]]
    )


def create_bot(token: str) -> Bot:
    return Bot(
        token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


class TelegramService:
    def __init__(
        self,
        bot: Any,  # aiogram Bot (or a fake with async send_message in tests)
        chat_id: int | None,
        database: Database,
        state: MonitorState,
        keywords: KeywordFile,
        send_interval: float = SEND_INTERVAL_SECONDS,
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.database = database
        self.state = state
        self.keywords = keywords
        self.send_interval = send_interval
        self._alerts: asyncio.Queue[str] = asyncio.Queue()
        self._edits: set[int] = set()  # lead ids whose message must be updated (scam verdict)
        self._wake = asyncio.Event()
        self.last_round_failed = False  # True if the last delivery round hit a network error

    # --- inputs from the pipeline / server ---------------------------------------------

    async def notify_lead(self, lead: StoredPost) -> None:
        """Lead handler for the pipeline: the lead is already in the database, just wake up."""
        self._wake.set()

    async def notify_verdict(self, post_id: int) -> None:
        """Scam check finished: the lead message (if already sent) gets edited."""
        self._edits.add(post_id)
        self._wake.set()

    async def notify_alert(self, alert: ExtensionAlert) -> None:
        await self.queue_text(format_alert(alert))

    async def queue_text(self, text: str) -> None:
        await self._alerts.put(text)
        self._wake.set()

    # --- delivery ---------------------------------------------------------------------------

    async def deliver_once(self) -> int:
        """Sends queued alerts, then pending leads. Returns how many messages were sent."""
        self.last_round_failed = False
        if self.chat_id is None:
            return 0
        sent = 0
        while not self._alerts.empty():
            text = self._alerts.get_nowait()
            if not await self._send(text):
                await self._alerts.put(text)  # keep it for the next round
                self.last_round_failed = True
                return sent
            sent += 1

        leads = await asyncio.to_thread(self.database.pending_leads)
        for lead in leads:
            result = await self._send_lead(lead)
            if result is None:  # network problem: retry later
                self.last_round_failed = True
                return sent
            sent += 1

        for post_id in sorted(self._edits):
            lead = await asyncio.to_thread(self.database.get_lead, post_id)
            if lead is None or not lead.get("telegram_message_id"):
                self._edits.discard(post_id)  # not sent yet: it will be sent with the verdict
                continue
            if await self._edit_lead(lead) is None:
                self.last_round_failed = True
                return sent
            self._edits.discard(post_id)
            sent += 1
        return sent

    def _format(self, lead: dict[str, Any]) -> str:
        location = self.keywords.get().found_in_group(lead["text"], "location")
        return format_lead(lead, location=location)

    async def _edit_lead(self, lead: dict[str, Any]) -> bool | None:
        try:
            result = await self._call(
                lambda: self.bot.edit_message_text(
                    text=self._format(lead),
                    chat_id=self.chat_id,
                    message_id=lead["telegram_message_id"],
                    reply_markup=_lead_markup(lead),
                )
            )
        except TelegramBadRequest as err:
            # e.g. "message is not modified" or the message was deleted — nothing to retry.
            log.info("Lead #%d message not edited: %s", lead["id"], err)
            return False
        return None if result is None else True

    async def _send_lead(self, lead: dict[str, Any]) -> bool | None:
        markup = _lead_markup(lead)
        try:
            message = await self._call(
                lambda: self.bot.send_message(self.chat_id, self._format(lead), reply_markup=markup)
            )
        except TelegramBadRequest as err:
            # The message itself is broken — retrying would fail forever. Skip it.
            log.error("Telegram rejected lead #%d: %s", lead["id"], err)
            await asyncio.to_thread(self.database.mark_notified, lead["id"], None)
            return False
        if message is None:
            return None
        await asyncio.to_thread(self.database.mark_notified, lead["id"], message.message_id)
        log.info("Lead #%d sent to Telegram", lead["id"])
        return True

    async def _send(self, text: str) -> bool:
        try:
            return await self._call(lambda: self.bot.send_message(self.chat_id, text)) is not None
        except TelegramBadRequest as err:
            log.error("Telegram rejected a message: %s", err)
            return True  # drop it

    async def _call(self, request: Callable[[], Awaitable[Any]]) -> Any | None:
        """Runs a Telegram request with rate limiting. None = temporary failure."""
        for _attempt in range(3):
            try:
                result = await request()
                await asyncio.sleep(self.send_interval)
                return result
            except TelegramRetryAfter as err:
                log.warning("Telegram asks to wait %s s", err.retry_after)
                await asyncio.sleep(err.retry_after + 1)
            except TelegramBadRequest:
                raise
            except TelegramForbiddenError:
                log.error("The bot was blocked or cannot write to chat %s — press Start in the bot", self.chat_id)
                return None
            except Exception as err:  # network errors, Telegram down
                log.warning("Telegram is unreachable: %s", err)
                return None
        return None

    async def run_delivery(self) -> None:
        if self.chat_id is None:
            log.warning("TELEGRAM_CHAT_ID is not set — leads are saved but not sent. Send /start to the bot.")
        while True:
            self._wake.clear()
            await self.deliver_once()
            if self.last_round_failed:
                await asyncio.sleep(NETWORK_ERROR_PAUSE_SECONDS)
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=DELIVERY_POLL_SECONDS)
            except TimeoutError:
                pass

    # --- "extension is silent" watch -------------------------------------------------------

    async def check_silence(self) -> None:
        state = self.state
        silent = state.seconds_since_seen()
        if state.silence_reported and silent is not None and silent < SILENCE_CHECK_SECONDS * 2:
            state.silence_reported = False
            await self.queue_text("✅ Розширення знову на зв'язку, моніторинг триває.")
        elif (
            state.extension_running
            and not state.silence_reported
            and silent is not None
            and silent > SILENCE_ALERT_SECONDS
        ):
            state.silence_reported = True
            await self.queue_text(
                f"⚠️ Розширення не виходить на зв'язок {int(silent // 60)} хв.\n"
                "Перевірте, що Chrome відкритий, а ПК не спить."
            )

    async def run_silence_watch(self) -> None:
        while True:
            await asyncio.sleep(SILENCE_CHECK_SECONDS)
            await self.check_silence()

    # --- commands -----------------------------------------------------------------------------

    def _authorized(self, message: Message) -> bool:
        if self.chat_id is not None and message.chat.id == self.chat_id:
            return True
        log.warning("Ignored a message from unknown chat %s", message.chat.id)
        return False

    def router(self) -> Router:
        router = Router(name="lead_monitor")

        @router.message(CommandStart())
        @router.message(Command("help"))
        async def on_start(message: Message) -> None:
            if self.chat_id is None:
                await message.answer(
                    f"Ваш chat ID: <code>{message.chat.id}</code>\n"
                    "Впишіть його в .env як TELEGRAM_CHAT_ID і перезапустіть програму."
                )
                return
            if self._authorized(message):
                await message.answer(HELP_TEXT)

        @router.message(Command("status"))
        async def on_status(message: Message) -> None:
            if not self._authorized(message):
                return
            stats = await asyncio.to_thread(self.database.stats)
            keyword_filter = self.keywords.get()
            await message.answer(
                format_status(self.state, stats, (len(keyword_filter.include), len(keyword_filter.exclude)))
            )

        @router.message(Command("pause"))
        async def on_pause(message: Message) -> None:
            if not self._authorized(message):
                return
            self.state.paused = True
            log.info("Monitoring paused from Telegram")
            await message.answer("⏸ Пауза. Розширення перестане відкривати групи (до 1 хв). /resume — продовжити.")

        @router.message(Command("resume"))
        async def on_resume(message: Message) -> None:
            if not self._authorized(message):
                return
            self.state.paused = False
            log.info("Monitoring resumed from Telegram")
            await message.answer("▶️ Продовжую моніторинг.")

        return router

    async def run_polling(self) -> None:
        dispatcher = Dispatcher()
        dispatcher.include_router(self.router())
        await dispatcher.start_polling(self.bot, handle_signals=False, close_bot_session=False)
