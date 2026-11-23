"""Scam check workflow: queue, profile result from the extension, cache, expiry, API, Telegram."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lead_monitor.core.models import FacebookPost
from lead_monitor.core.state import MonitorState
from lead_monitor.filters.keywords import KeywordFile, KeywordMatch
from lead_monitor.notifications.formatting import format_lead
from lead_monitor.notifications.telegram import TelegramService
from lead_monitor.scam.rules import ProfileSignals, ScamRules
from lead_monitor.scam.service import NOTE_PROFILE_NOT_CHECKED, ScamChecker
from lead_monitor.server.extension_api import TOKEN_HEADER, create_app
from lead_monitor.storage.database import Database, StoredPost

PROFILE = "https://www.facebook.com/profile.php?id=42"
GOOD_PROFILE = ProfileSignals(has_photo=True, friends=300, joined_year=2012, intro_items=3)
BAD_PROFILE = ProfileSignals(has_photo=False, friends=4, joined_year=2026, intro_items=0)


def make_post(n: int, text: str = "Fire stopper required in Greenwich £27.50 per hour",
              profile: str | None = PROFILE, author: str | None = "Ivan Petrenko") -> FacebookPost:
    return FacebookPost(
        group_id="g1",
        post_url=f"https://www.facebook.com/groups/g1/posts/{n}/",
        author_name=author,
        author_profile_url=profile,
        text=text,
    )


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[ScamChecker, Database, list[int]]]:
    db = Database(tmp_path / "monitor.db")
    verdicts: list[int] = []

    async def on_verdict(post_id: int) -> None:
        verdicts.append(post_id)

    yield ScamChecker(db, ScamRules(), [on_verdict]), db, verdicts
    db.close()


def add_lead(db: Database, post: FacebookPost) -> StoredPost:
    stored = db.add_post(post, KeywordMatch(is_lead=True, matched=["fire stop*"]))
    assert stored is not None
    return stored


def test_profile_is_queued_then_verdict_after_extension_result(env) -> None:
    checker, db, verdicts = env
    lead = add_lead(db, make_post(1))
    asyncio.run(checker.on_new_lead(lead))
    assert db.get_lead(lead.id)["scam_level"] == "pending"
    task = asyncio.run(checker.next_task())
    assert task["profile_url"] == PROFILE

    assert asyncio.run(checker.complete(task["id"], GOOD_PROFILE)) is True
    row = db.get_lead(lead.id)
    assert row["scam_level"] == "green"
    assert row["scam_red"] == []
    assert verdicts == [lead.id]
    assert asyncio.run(checker.next_task()) is None
    # a second result for the same check is ignored
    assert asyncio.run(checker.complete(task["id"], BAD_PROFILE)) is False


def test_bad_profile_gives_red(env) -> None:
    checker, db, _ = env
    lead = add_lead(db, make_post(1))
    asyncio.run(checker.on_new_lead(lead))
    task = asyncio.run(checker.next_task())
    asyncio.run(checker.complete(task["id"], BAD_PROFILE))
    row = db.get_lead(lead.id)
    assert row["scam_level"] == "red"
    assert "Немає фото профілю" in row["scam_red"]


def test_anonymous_post_gets_verdict_at_once(env) -> None:
    checker, db, verdicts = env
    lead = add_lead(db, make_post(1, profile=None, author="Anonymous participant"))
    asyncio.run(checker.on_new_lead(lead))
    row = db.get_lead(lead.id)
    assert row["scam_level"] == "yellow"
    assert row["scam_red"] == ["Анонімний допис (автор прихований)"]
    assert asyncio.run(checker.next_task()) is None
    assert verdicts == [lead.id]


def test_scam_text_and_anonymous_is_red(env) -> None:
    checker, db, _ = env
    text = "Fire stopper required in London, pay admin fee first, contact only on Telegram"
    lead = add_lead(db, make_post(1, text=text, profile=None))
    asyncio.run(checker.on_new_lead(lead))
    assert db.get_lead(lead.id)["scam_level"] == "red"


def test_same_author_uses_cached_profile(env) -> None:
    checker, db, _ = env
    first = add_lead(db, make_post(1))
    asyncio.run(checker.on_new_lead(first))
    asyncio.run(checker.complete(asyncio.run(checker.next_task())["id"], GOOD_PROFILE))

    second = add_lead(db, make_post(2, text="Fire door installer needed in Croydon £220 per day"))
    asyncio.run(checker.on_new_lead(second))
    assert db.get_lead(second.id)["scam_level"] == "green"
    assert asyncio.run(checker.next_task()) is None  # profile not reopened


def test_two_leads_same_profile_one_visit(env) -> None:
    checker, db, verdicts = env
    a = add_lead(db, make_post(1))
    b = add_lead(db, make_post(2, text="Fire stopper needed in Stratford £25ph"))
    asyncio.run(checker.on_new_lead(a))
    asyncio.run(checker.on_new_lead(b))
    asyncio.run(checker.complete(asyncio.run(checker.next_task())["id"], GOOD_PROFILE))
    assert sorted(verdicts) == [a.id, b.id]
    assert asyncio.run(checker.next_task()) is None


def test_profile_error_gives_verdict_without_profile(env) -> None:
    checker, db, _ = env
    lead = add_lead(db, make_post(1))
    asyncio.run(checker.on_new_lead(lead))
    asyncio.run(checker.complete(asyncio.run(checker.next_task())["id"], ProfileSignals(status="error")))
    row = db.get_lead(lead.id)
    assert row["scam_level"] == "yellow"
    assert row["scam_red"] == ["ℹ️ Профіль автора не вдалося відкрити"]


def test_expired_check_gets_verdict_without_profile(env) -> None:
    checker, db, _ = env
    lead = add_lead(db, make_post(1))
    asyncio.run(checker.on_new_lead(lead))
    db._conn.execute("UPDATE profile_checks SET requested_at = '2000-01-01T00:00:00+00:00'")
    assert asyncio.run(checker.expire()) == 1
    row = db.get_lead(lead.id)
    assert row["scam_level"] == "yellow"
    assert row["scam_red"] == [NOTE_PROFILE_NOT_CHECKED]


# --- message texts --------------------------------------------------------------------------


def lead_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": 1, "group_id": "g1", "group_name": "G", "author_name": "Ivan", "author_profile_url": PROFILE,
        "post_url": "https://www.facebook.com/groups/g1/posts/1/", "text": "Fire stopper required £25ph",
        "matched_keywords": [], "scam_level": None, "scam_red": [], "scam_green": [],
    }
    row.update(overrides)
    return row


def test_scam_lines_in_message() -> None:
    assert "Перевіряю автора" in format_lead(lead_row(scam_level="pending"))
    green = format_lead(lead_row(scam_level="green", scam_green=["Є фото профілю"]))
    assert "🟢 Явних ознак скаму не знайдено" in green and "✓ Є фото профілю" in green
    red = format_lead(lead_row(scam_level="red", scam_red=["Немає фото профілю", "Мало друзів (3)"]))
    assert "🔴 <b>Схоже на скам</b>" in red and "• Мало друзів (3)" in red
    yellow = format_lead(lead_row(scam_level="yellow"))
    assert "🟡" in yellow and "Мало даних про автора" in yellow
    note = format_lead(lead_row(scam_level="yellow", scam_red=[NOTE_PROFILE_NOT_CHECKED]))
    assert NOTE_PROFILE_NOT_CHECKED in note and "• ℹ️" not in note
    assert "Перевіряю" not in format_lead(lead_row())  # old leads: no scam block


# --- Telegram: send with "checking...", then edit ---------------------------------------------


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edited: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup: Any = None) -> Any:
        self.sent.append(text)
        return SimpleNamespace(message_id=500 + len(self.sent))

    async def edit_message_text(self, text: str, chat_id: int, message_id: int, reply_markup: Any = None) -> Any:
        self.edited.append((message_id, text))
        return True


def test_telegram_message_is_edited_with_verdict(env, tmp_path: Path) -> None:
    checker, db, _ = env
    bot = FakeBot()
    telegram = TelegramService(bot, 1, db, MonitorState(), KeywordFile(tmp_path / "kw.txt"), send_interval=0)
    checker.verdict_handlers.append(telegram.notify_verdict)

    async def scenario() -> None:
        lead = add_lead(db, make_post(1))
        await checker.on_new_lead(lead)
        await telegram.deliver_once()  # sent with "checking..."
        task = await checker.next_task()
        await checker.complete(task["id"], BAD_PROFILE)
        await telegram.deliver_once()  # edited with the verdict

    asyncio.run(scenario())
    assert len(bot.sent) == 1 and "Перевіряю автора" in bot.sent[0]
    assert len(bot.edited) == 1
    message_id, text = bot.edited[0]
    assert message_id == 501 and "🔴" in text


# --- API ----------------------------------------------------------------------------------------


def test_api_gives_profile_task_and_accepts_result(env) -> None:
    checker, db, _ = env
    lead = add_lead(db, make_post(1))
    asyncio.run(checker.on_new_lead(lead))
    auth = {TOKEN_HEADER: "t"}

    async def scenario() -> tuple[Any, Any, int]:
        async with TestClient(TestServer(create_app("t", scam_checker=checker))) as client:
            control = await (await client.get("/api/control", headers=auth)).json()
            check_id = control["profile_check"]["id"]
            result = await client.post(
                "/api/profile_result", headers=auth,
                json={"check_id": check_id, "profile": GOOD_PROFILE.model_dump()},
            )
            bad = await client.post("/api/profile_result", headers=auth, json={"nope": 1})
            return control, await result.json(), bad.status

    control, result, bad_status = asyncio.run(scenario())
    assert control["profile_check"]["profile_url"] == PROFILE
    assert result == {"ok": True}
    assert bad_status == 400
    assert db.get_lead(lead.id)["scam_level"] == "green"


def test_paused_monitor_gets_no_profile_task(env) -> None:
    checker, db, _ = env
    asyncio.run(checker.on_new_lead(add_lead(db, make_post(1))))

    async def scenario() -> Any:
        app = create_app("t", scam_checker=checker, state=MonitorState(paused=True))
        async with TestClient(TestServer(app)) as client:
            return await (await client.get("/api/control", headers={TOKEN_HEADER: "t"})).json()

    assert asyncio.run(scenario()) == {"paused": True, "profile_check": None}


def test_many_red_reasons_are_shortened() -> None:
    red = [f"reason {i}" for i in range(6)]
    text = format_lead(lead_row(scam_level="red", scam_red=red))
    assert "• reason 3" in text and "• reason 4" not in text and "…і ще 2" in text
