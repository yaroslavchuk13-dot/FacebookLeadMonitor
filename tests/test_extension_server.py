"""Tests for the local extension server (no real network port is used)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from extension_server import MAX_POSTS_PER_REQUEST, TOKEN_HEADER, create_app
from models import FacebookPost

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
