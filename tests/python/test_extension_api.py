"""Tests for the local extension server (no real network port is used)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lead_monitor.core.models import ExtensionAlert, FacebookPost
from lead_monitor.server.extension_api import MAX_POSTS_PER_REQUEST, TOKEN_HEADER, create_app

TOKEN = "test-token-123"
AUTH = {TOKEN_HEADER: TOKEN}

VALID_POST = {
    "group_id": "123",
    "post_url": "https://www.facebook.com/groups/123/posts/456/",
    "author_name": "Ivan",
    "author_profile_url": "https://www.facebook.com/profile.php?id=789",
    "text": "Шукаю сантехніка",
}


def call(fn: Callable[[TestClient], Awaitable[Any]]) -> tuple[Any, list[FacebookPost]]:
    """Run `fn(client)` against a fresh app; return its result and received posts."""
    received: list[FacebookPost] = []

    async def sink(posts: list[FacebookPost]) -> None:
        received.extend(posts)

    async def runner() -> Any:
        async with TestClient(TestServer(create_app(TOKEN, sink))) as client:
            return await fn(client)

    return asyncio.run(runner()), received


async def post_json(client: TestClient, body: Any, headers: dict[str, str] = AUTH):
    resp = await client.post("/api/posts", json=body, headers=headers)
    return resp.status, await resp.json()


def test_empty_token_not_allowed() -> None:
    with pytest.raises(ValueError):
        create_app("")


def test_health_without_token() -> None:
    async def fn(client: TestClient):
        resp = await client.get("/health")
        return resp.status, await resp.json()

    (status, data), _ = call(fn)
    assert status == 200 and data == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {TOKEN_HEADER: "wrong"}, {TOKEN_HEADER: ""}])
def test_posts_require_valid_token(headers: dict[str, str]) -> None:
    (status, _), received = call(lambda c: post_json(c, {"posts": [VALID_POST]}, headers))
    assert status == 401
    assert received == []


def test_valid_posts_accepted() -> None:
    body = {"posts": [VALID_POST, {**VALID_POST, "post_url": VALID_POST["post_url"] + "?x=1"}]}
    (status, data), received = call(lambda c: post_json(c, body))
    assert status == 200
    assert data == {"accepted": 2, "rejected": 0}
    assert [p.group_id for p in received] == ["123", "123"]


def test_invalid_posts_rejected_individually() -> None:
    body = {"posts": [VALID_POST, {**VALID_POST, "text": ""}, {"junk": True}]}
    (status, data), received = call(lambda c: post_json(c, body))
    assert status == 200
    assert data == {"accepted": 1, "rejected": 2}
    assert len(received) == 1


def test_all_invalid_does_not_call_sink() -> None:
    (status, data), received = call(lambda c: post_json(c, {"posts": [{"junk": 1}]}))
    assert data == {"accepted": 0, "rejected": 1}
    assert received == []


@pytest.mark.parametrize(
    "body",
    [[], {"posts": "nope"}, {"other": []}, {"posts": [VALID_POST] * (MAX_POSTS_PER_REQUEST + 1)}],
)
def test_bad_body_shape(body: Any) -> None:
    (status, _), received = call(lambda c: post_json(c, body))
    assert status == 400
    assert received == []


def test_invalid_json() -> None:
    async def fn(client: TestClient):
        resp = await client.post("/api/posts", data=b"{not json", headers=AUTH)
        return resp.status

    status, _ = call(fn)
    assert status == 400


# --- /api/alert ---------------------------------------------------------------


def send_alert(body: Any, headers: dict[str, str] = AUTH) -> tuple[int, list[ExtensionAlert]]:
    """POST `body` to /api/alert; return the status and the alerts the sink received."""
    alerts: list[ExtensionAlert] = []

    async def alert_sink(alert: ExtensionAlert) -> None:
        alerts.append(alert)

    async def runner() -> int:
        app = create_app(TOKEN, alert_sink=alert_sink)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/alert", json=body, headers=headers)
            return resp.status

    return asyncio.run(runner()), alerts


def test_alert_accepted() -> None:
    body = {"kind": "checkpoint", "message": "Facebook checkpoint", "group_id": "1", "stopped": True}
    status, alerts = send_alert(body)
    assert status == 200
    assert len(alerts) == 1
    assert alerts[0].kind == "checkpoint" and alerts[0].stopped is True


def test_alert_requires_token() -> None:
    status, alerts = send_alert({"kind": "error", "message": "x"}, headers={})
    assert status == 401 and alerts == []


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "unknown", "message": "x"},
        {"kind": "error", "message": ""},
        {"kind": "error", "message": "x" * 501},
        {"message": "no kind"},
        ["not", "an", "object"],
    ],
)
def test_invalid_alert_rejected(body: Any) -> None:
    status, alerts = send_alert(body)
    assert status == 400 and alerts == []


# --- /api/control (pause from Telegram) and the "alive" mark -----------------------------


def test_control_reports_pause_and_marks_extension_alive() -> None:
    from lead_monitor.core.state import MonitorState

    state = MonitorState(paused=True)

    async def runner() -> tuple[int, Any, int]:
        async with TestClient(TestServer(create_app(TOKEN, state=state))) as client:
            ok = await client.get("/api/control", headers=AUTH)
            denied = await client.get("/api/control")
            return ok.status, await ok.json(), denied.status

    status, data, denied_status = asyncio.run(runner())
    assert status == 200 and data == {"paused": True}
    assert denied_status == 401
    assert state.extension_running is True
    assert state.seconds_since_seen() is not None and state.seconds_since_seen() < 5
