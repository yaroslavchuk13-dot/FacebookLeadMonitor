"""Local HTTP server that receives posts from the Chrome extension.

Listens only on 127.0.0.1. Every /api/* request must carry the shared token
in the X-Extension-Token header. Run: `python -m lead_monitor.server`.
"""

import hmac
import json
import logging
from collections.abc import Awaitable, Callable

from aiohttp import web
from pydantic import ValidationError

from lead_monitor.core.config import get_settings
from lead_monitor.core.log_setup import setup_logging
from lead_monitor.core.models import ExtensionAlert, FacebookPost

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
TOKEN_HEADER = "X-Extension-Token"
MAX_POSTS_PER_REQUEST = 100
MAX_BODY_BYTES = 2_000_000

PostSink = Callable[[list[FacebookPost]], Awaitable[None]]
AlertSink = Callable[[ExtensionAlert], Awaitable[None]]

TOKEN_KEY = web.AppKey("token", str)
SINK_KEY = web.AppKey("sink", PostSink)
ALERT_SINK_KEY = web.AppKey("alert_sink", AlertSink)


async def log_sink(posts: list[FacebookPost]) -> None:
    """Temporary sink: just log posts. Stage 4 replaces it with SQLite."""
    for post in posts:
        preview = post.text[:80].replace("\n", " ")
        log.info("Post | group=%s | %s | %s", post.group_id, post.post_url, preview)


async def log_alert_sink(alert: ExtensionAlert) -> None:
    """Temporary alert sink: log only. M3 also sends alerts to Telegram."""
    log.warning(
        "ALERT from extension | %s | group=%s | stopped=%s | %s",
        alert.kind, alert.group_id, alert.stopped, alert.message,
    )


@web.middleware
async def auth_middleware(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    if request.path.startswith("/api/"):
        given = request.headers.get(TOKEN_HEADER, "")
        expected = request.app[TOKEN_KEY]
        if not hmac.compare_digest(given.encode(), expected.encode()):
            log.warning("Rejected request to %s: bad or missing token", request.path)
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def receive_posts(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "invalid JSON"}, status=400)

    items = body.get("posts") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return web.json_response({"error": "'posts' must be a list"}, status=400)
    if len(items) > MAX_POSTS_PER_REQUEST:
        return web.json_response({"error": "too many posts"}, status=400)

    accepted: list[FacebookPost] = []
    rejected = 0
    for index, item in enumerate(items):
        try:
            accepted.append(FacebookPost.model_validate(item))
        except ValidationError as exc:
            rejected += 1
            # Log only field names, not values (they may contain personal data).
            fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
            log.warning("Rejected post #%d: invalid fields %s", index, fields)

    if accepted:
        await request.app[SINK_KEY](accepted)
    log.info("Received %d posts (%d rejected)", len(accepted), rejected)
    return web.json_response({"accepted": len(accepted), "rejected": rejected})


async def receive_alert(request: web.Request) -> web.Response:
    try:
        alert = ExtensionAlert.model_validate(await request.json())
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError):
        return web.json_response({"error": "invalid alert"}, status=400)
    await request.app[ALERT_SINK_KEY](alert)
    return web.json_response({"ok": True})


def create_app(
    token: str, sink: PostSink = log_sink, alert_sink: AlertSink = log_alert_sink
) -> web.Application:
    if not token:
        raise ValueError("Extension token must not be empty")
    app = web.Application(middlewares=[auth_middleware], client_max_size=MAX_BODY_BYTES)
    app[TOKEN_KEY] = token
    app[SINK_KEY] = sink
    app[ALERT_SINK_KEY] = alert_sink
    app.router.add_get("/health", health)
    app.router.add_post("/api/posts", receive_posts)
    app.router.add_post("/api/alert", receive_alert)
    return app


def main() -> int:
    settings = get_settings()
    setup_logging(settings)
    if settings.extension_token is None:
        log.error("EXTENSION_TOKEN is not set in .env — refusing to start the server")
        return 1
    app = create_app(settings.extension_token.get_secret_value())
    log.info("Extension server listening on http://%s:%d", HOST, settings.extension_port)
    web.run_app(app, host=HOST, port=settings.extension_port, print=None, access_log=None)
    return 0
