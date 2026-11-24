"""The whole program in one process: extension API server + pipeline + Telegram bot.

Run: `python -m lead_monitor` (or scripts\\start_server.ps1). Stop: Ctrl+C.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from aiohttp import web

from lead_monitor.core.config import BASE_DIR, Settings, get_settings
from lead_monitor.core.log_setup import setup_logging
from lead_monitor.core.models import ExtensionAlert, FacebookPost
from lead_monitor.core.state import MonitorState
from lead_monitor.filters.keywords import KeywordFile
from lead_monitor.pipeline import PostProcessor, log_lead
from lead_monitor.scam.rules import ScamRules
from lead_monitor.scam.service import ScamChecker
from lead_monitor.server.extension_api import HOST, create_app, log_alert_sink, port_is_free
from lead_monitor.storage.database import Database

log = logging.getLogger(__name__)

RESTART_DELAY_SECONDS = 30
MAX_RESTART_DELAY_SECONDS = 15 * 60
STABLE_RUN_SECONDS = 10 * 60  # a task that ran this long counts as healthy again


def restart_delay(attempt: int, error: BaseException) -> float:
    """Exponential backoff (30 s, 60 s, 120 s ... 15 min); never shorter than Telegram's retry_after.

    Restarting sooner than Telegram asks only extends its flood ban.
    """
    delay = min(RESTART_DELAY_SECONDS * 2 ** max(0, attempt - 1), MAX_RESTART_DELAY_SECONDS)
    retry_after = getattr(error, "retry_after", None)
    if isinstance(retry_after, (int, float)):
        delay = max(delay, retry_after + 5)
    return delay


async def supervise(name: str, task: Callable[[], Awaitable[None]]) -> None:
    """Keeps a background task alive: logs a crash and restarts it with growing pauses."""
    attempt = 0
    while True:
        started = time.monotonic()
        try:
            await task()
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if time.monotonic() - started > STABLE_RUN_SECONDS:
                attempt = 0
            attempt += 1
            delay = restart_delay(attempt, error)
            log.error("%s failed (%s) — restarting in %d s", name, error, delay)
            log.debug("Details of the %s failure", name, exc_info=True)
            await asyncio.sleep(delay)


def _parse_chat_id(settings: Settings) -> int | None:
    if not settings.telegram_chat_id:
        return None
    try:
        return int(settings.telegram_chat_id)
    except ValueError:
        log.error("TELEGRAM_CHAT_ID must be a number, got %r — Telegram disabled", settings.telegram_chat_id)
        return None


async def run(settings: Settings) -> None:
    database = Database(settings.database_path)
    keywords = KeywordFile(settings.keywords_path)
    keywords.get()  # log the loaded keywords at startup
    state = MonitorState()
    log.info("Database: %s | %s", settings.database_path, database.stats())

    telegram = None
    bot = None
    if settings.telegram_bot_token is not None:
        from lead_monitor.notifications.telegram import TelegramService, create_bot

        bot = create_bot(settings.telegram_bot_token.get_secret_value())
        telegram = TelegramService(bot, _parse_chat_id(settings), database, state, keywords)
    else:
        log.warning("TELEGRAM_BOT_TOKEN is not set — leads are only saved and logged")

    scam_rules = ScamRules.load(BASE_DIR / "config" / "scam_rules.toml")
    scam = ScamChecker(database, scam_rules, [telegram.notify_verdict] if telegram else [])
    # Order matters: the scam check runs first, so a ready verdict goes into the first message.
    handlers = [log_lead, scam.on_new_lead] + ([telegram.notify_lead] if telegram else [])
    processor = PostProcessor(database, keywords, handlers, max_age_hours=settings.lead_max_age_hours)

    async def posts_sink(posts: list[FacebookPost]) -> None:
        state.last_posts_at = time.time()
        await processor.handle_posts(posts)

    async def alert_sink(alert: ExtensionAlert) -> None:
        await log_alert_sink(alert)
        if alert.kind == "started":
            state.extension_running = True
            state.silence_reported = False
        elif alert.stopped:
            state.extension_running = False
        if telegram:
            await telegram.notify_alert(alert)

    app = create_app(
        settings.extension_token.get_secret_value(),
        sink=posts_sink,
        alert_sink=alert_sink,
        state=state,
        scam_checker=scam,
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, HOST, settings.extension_port).start()
    log.info("Extension server listening on http://%s:%d", HOST, settings.extension_port)

    tasks = [supervise("Scam check expiry", scam.run_expiry)]
    if telegram:
        tasks += [
            supervise("Telegram polling", telegram.run_polling),
            supervise("Telegram delivery", telegram.run_delivery),
            supervise("Silence watch", telegram.run_silence_watch),
        ]
        log.info("Telegram bot started")
    try:
        await asyncio.gather(*tasks)  # runs until Ctrl+C
    finally:
        await runner.cleanup()
        if bot is not None:
            await bot.session.close()
        database.close()
        log.info("Stopped")


def main() -> int:
    settings = get_settings()
    setup_logging(settings)
    if settings.extension_token is None:
        log.error("EXTENSION_TOKEN is not set in .env — refusing to start")
        return 1
    if not port_is_free(settings.extension_port):
        log.error(
            "Port %d is already in use — the program is probably already running in another "
            "terminal window. Close it first or keep using it.",
            settings.extension_port,
        )
        return 1
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        log.info("Stopped by Ctrl+C")
    return 0
