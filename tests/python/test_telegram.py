"""Tests for Telegram formatting and delivery (no network: the bot is a fake)."""

import asyncio
import time
from datetime import UTC, datetime
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest

from lead_monitor.core.models import ExtensionAlert, FacebookPost
from lead_monitor.core.state import MonitorState
from lead_monitor.filters.keywords import KeywordFile, KeywordMatch
from lead_monitor.notifications import telegram as telegram_module
from lead_monitor.notifications.formatting import (
    MAX_TEXT_CHARS,
    format_alert,
    format_lead,
    format_status,
    lead_button_text,
    lead_title,
)
from lead_monitor.notifications.telegram import TelegramService
from lead_monitor.storage.database import Database

CHAT_ID = 111

LEAD = {
    "id": 1,
    "group_id": "g1",
    "group_name": "Fire <Stoppers> & Co",
    "author_name": "Ivan",
    "author_profile_url": "https://www.facebook.com/profile.php?id=7&x=1",
    "post_url": "https://www.facebook.com/groups/g1/posts/9/",
    "text": "Need <b>fire stoppers</b> & sprayers",
    "matched_keywords": ["fire stop*"],
}


# --- formatting --------------------------------------------------------------------------


def test_lead_message_is_html_escaped() -> None:
    text = format_lead(LEAD)
    assert "Fire &lt;Stoppers&gt; &amp; Co" in text
    assert "Need &lt;b&gt;fire stoppers&lt;/b&gt; &amp; sprayers" in text
    assert '<a href="https://www.facebook.com/profile.php?id=7&amp;x=1">Ivan</a>' in text
    assert lead_button_text(LEAD) == "🔗 Відкрити допис"


def test_message_has_separate_lines() -> None:
    lead = {
        **LEAD,
        "text": "MKA require 2 fire stoppers for a project in Greenwich.\nStart date - ASAP.\n£27.50 per hour",
        "posted_at": "2026-11-24T13:40:00+00:00",
    }
    now = datetime(2026, 11, 24, 17, 40, tzinfo=UTC)
    lines = format_lead(lead, location=["Greenwich"], now=now).split("\n")
    assert lines[0] == "🕒 <b>4 год тому (24.11 13:40)</b>"
    assert lines[1] == "🔥 <b>MKA require 2 fire stoppers for a project in Greenwich.</b>"
    assert "💷 <b>Оплата:</b> £27.50/год (≈ £220 за 8-год день)" in lines
    assert "📍 <b>Місце:</b> Greenwich" in lines
    assert "ℹ️ <b>Додатково:</b>" in lines and "• Start date - ASAP" in lines
    assert "👥 <b>Група:</b> Fire &lt;Stoppers&gt; &amp; Co" in lines
    assert "<blockquote expandable>MKA require" in "\n".join(lines)
    assert lines[-1].endswith("</blockquote>")


def test_title_from_short_first_line() -> None:
    assert lead_title("Linsco Recruitment\nFire Door Installers required in Watford") == (
        "Linsco Recruitment — Fire Door Installers required in Watford"
    )
    assert lead_title("x" * 200).endswith("…")
    assert lead_title("   ") == "Вакансія"


def test_anonymous_lead_and_unknown_date() -> None:
    text = format_lead({**LEAD, "author_name": None, "author_profile_url": None, "matched_keywords": []})
    assert "👤 <b>Автор:</b> Анонімно" in text
    assert "🕒 <b>Дата допису невідома</b>" in text
    assert "📞 <b>Контакт:</b> не вказано — напишіть автору" in text


def test_fallback_link_is_explained() -> None:
    lead = {**LEAD, "post_url": "https://www.facebook.com/groups/g1/?flm_post=abc"}
    assert "Посилання на сам допис не знайдено" in format_lead(lead)
    assert lead_button_text(lead) == "🔗 Відкрити групу"


def test_long_text_is_truncated() -> None:
    text = format_lead({**LEAD, "text": "x" * (MAX_TEXT_CHARS + 500)})
    assert len(text) < 4096
    assert text.endswith("…</blockquote>")


def test_alert_text() -> None:
    alert = ExtensionAlert(kind="checkpoint", message="Facebook checkpoint", stopped=True)
    assert format_alert(alert) == "⛔ Facebook checkpoint\n<i>Моніторинг зупинено.</i>"
    manual = ExtensionAlert(kind="stopped", message="Stopped by user", stopped=True)
    assert format_alert(manual) == "⏹ Stopped by user"


def test_status_text() -> None:
    state = MonitorState(paused=True)
    stats = {"total": 10, "leads": 3, "duplicates": 1, "groups": 2}
    text = format_status(state, stats, (0, 0))
    assert "пауза" in text and "10 дописів, 3 лідів" in text and "вимкнено" in text
    state = MonitorState(extension_running=True, last_seen=time.time() - 30)
    assert "працює" in format_status(state, stats, (5, 1))
    assert "30 с тому" in format_status(state, stats, (5, 1))


# --- delivery ------------------------------------------------------------------------------


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None

    async def send_message(self, chat_id: int, text: str, reply_markup: Any = None) -> Any:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        return SimpleNamespace(message_id=1000 + len(self.sent))


@pytest.fixture
def service(tmp_path: Path) -> Iterator[tuple[TelegramService, FakeBot, Database]]:
    db = Database(tmp_path / "monitor.db")
    bot = FakeBot()
    svc = TelegramService(bot, CHAT_ID, db, MonitorState(), KeywordFile(tmp_path / "kw.txt"), send_interval=0)
    yield svc, bot, db
    db.close()


def add_lead(db: Database, n: int, is_lead: bool = True) -> None:
    post = FacebookPost(
        group_id="g1",
        post_url=f"https://www.facebook.com/groups/g1/posts/{n}/",
        author_name=f"A{n}",
        text=f"lead text {n}",
    )
    stored = db.add_post(post, KeywordMatch(is_lead=is_lead, matched=["kw"] if is_lead else []))
    if is_lead:  # as the scam checker does right after saving
        db.set_scam_result(stored.id, "pending", [], [])


def test_pending_leads_are_sent_once_in_order(service) -> None:
    svc, bot, db = service
    add_lead(db, 1)
    add_lead(db, 2, is_lead=False)
    add_lead(db, 3)
    assert asyncio.run(svc.deliver_once()) == 2
    assert ["lead text 1" in m["text"] for m in bot.sent] == [True, False]
    assert "lead text 3" in bot.sent[1]["text"]
    assert all(m["chat_id"] == CHAT_ID for m in bot.sent)
    assert bot.sent[0]["markup"].inline_keyboard[0][0].url.endswith("/posts/1/")
    # Already delivered -> nothing on the next round.
    assert asyncio.run(svc.deliver_once()) == 0
    assert db.pending_leads() == []


def test_network_error_keeps_leads_for_later(service) -> None:
    svc, bot, db = service
    add_lead(db, 1)
    bot.fail_with = ConnectionError("no internet")
    assert asyncio.run(svc.deliver_once()) == 0
    assert svc.last_round_failed
    assert len(db.pending_leads()) == 1

    bot.fail_with = None  # internet is back
    assert asyncio.run(svc.deliver_once()) == 1
    assert not svc.last_round_failed


def test_rejected_message_is_skipped_not_retried_forever(service) -> None:
    svc, bot, db = service
    add_lead(db, 1)
    bot.fail_with = TelegramBadRequest(method=None, message="Bad Request: can't parse entities")
    asyncio.run(svc.deliver_once())
    assert db.pending_leads() == []


def test_alerts_go_before_leads(service) -> None:
    svc, bot, db = service
    add_lead(db, 1)

    async def scenario() -> None:
        await svc.notify_alert(ExtensionAlert(kind="checkpoint", message="Checkpoint!", stopped=True))
        await svc.deliver_once()

    asyncio.run(scenario())
    assert bot.sent[0]["text"].startswith("⛔ Checkpoint!")
    assert "lead text 1" in bot.sent[1]["text"]


def test_without_chat_id_nothing_is_sent_and_leads_wait(tmp_path: Path) -> None:
    db = Database(tmp_path / "monitor.db")
    bot = FakeBot()
    svc = TelegramService(bot, None, db, MonitorState(), KeywordFile(tmp_path / "kw.txt"), send_interval=0)
    add_lead(db, 1)
    assert asyncio.run(svc.deliver_once()) == 0
    assert bot.sent == [] and len(db.pending_leads()) == 1
    db.close()


def test_silence_alert_and_recovery(service, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, bot, _db = service
    state = svc.state
    state.extension_running = True
    state.last_seen = time.time() - telegram_module.SILENCE_ALERT_SECONDS - 60

    async def scenario() -> None:
        await svc.check_silence()
        await svc.check_silence()  # reported only once
        await svc.deliver_once()
        state.touch()  # the extension is back
        await svc.check_silence()
        await svc.deliver_once()

    asyncio.run(scenario())
    assert len(bot.sent) == 2
    assert "не виходить на зв'язок" in bot.sent[0]["text"]
    assert "знову на зв'язку" in bot.sent[1]["text"]


def test_no_silence_alert_when_monitoring_is_stopped(service) -> None:
    svc, bot, _db = service
    svc.state.extension_running = False
    svc.state.last_seen = time.time() - 10_000
    asyncio.run(svc.check_silence())
    asyncio.run(svc.deliver_once())
    assert bot.sent == []


def test_real_bot_object_can_be_created() -> None:
    """Catches wrong aiogram arguments (no network: the bot is only constructed)."""
    bot = telegram_module.create_bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    assert bot.default.parse_mode == "HTML"
    asyncio.run(bot.session.close())


def test_lead_message_shows_pay() -> None:
    lead = {**LEAD, "text": "Fire stopper required in Moorgate\n9hrs paid\nContract rate £25/h"}
    assert "💷 <b>Оплата:</b> £25/год (≈ £225 за 9-год день)" in format_lead(lead)
    no_pay = {**LEAD, "text": "Fire stopper required in Moorgate, rate negotiable"}
    assert "💷 <b>Оплата:</b> Оплата не вказана" not in format_lead(no_pay)
    assert "💷 <b>Оплата:</b> не вказана" in format_lead(no_pay)


def test_message_shows_how_fast_the_post_was_found() -> None:
    now = datetime(2026, 11, 24, 19, 10, tzinfo=UTC)
    lead = {**LEAD, "posted_at": "2026-11-24T19:03:00+00:00", "saved_at": "2026-11-24T19:05:10+00:00"}
    assert "🕒 <b>7 хв тому (24.11 19:03) · знайдено через 2 хв</b>" in format_lead(lead, now=now)
    old = {**LEAD, "posted_at": "2026-11-20T10:00:00+00:00", "saved_at": "2026-11-24T19:05:10+00:00"}
    assert "знайдено" not in format_lead(old, now=now)
