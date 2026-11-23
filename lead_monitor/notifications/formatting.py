"""Telegram message texts (HTML parse mode). Pure functions, unit-tested."""

import time
from html import escape
from typing import Any

from lead_monitor.core.models import ExtensionAlert
from lead_monitor.core.state import MonitorState
from lead_monitor.filters.pay import describe_pay

MAX_TEXT_CHARS = 3500  # Telegram limit is 4096 for the whole message
FALLBACK_LINK_MARK = "flm_post="  # see extension/content/post_links.js fallbackPostUrl

ALERT_ICONS = {
    "checkpoint": "⛔",
    "login_required": "🔑",
    "no_feed": "⚠️",
    "error": "⚠️",
    "started": "▶️",
    "stopped": "⏹",
}


def is_fallback_link(url: str) -> bool:
    return FALLBACK_LINK_MARK in url


def format_lead(lead: dict[str, Any]) -> str:
    group = escape(lead.get("group_name") or lead["group_id"])
    author = escape(lead.get("author_name") or "Анонімно")
    profile = lead.get("author_profile_url")
    author_line = f'👤 <a href="{escape(profile, quote=True)}">{author}</a>' if profile else f"👤 {author}"

    text = lead["text"]
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rstrip() + "…"

    lines = [f"🔔 <b>Новий лід</b> · {group}", f"💷 <b>{escape(describe_pay(lead['text']))}</b>", author_line]
    keywords = lead.get("matched_keywords") or []
    if keywords:
        lines.append("🔑 " + escape(", ".join(keywords)))
    lines += ["", escape(text)]
    if is_fallback_link(lead["post_url"]):
        lines += ["", "<i>Посилання на сам допис не знайдено — кнопка відкриє групу.</i>"]
    return "\n".join(lines)


def lead_button_text(lead: dict[str, Any]) -> str:
    return "🔗 Відкрити групу" if is_fallback_link(lead["post_url"]) else "🔗 Відкрити допис"


def format_alert(alert: ExtensionAlert) -> str:
    icon = ALERT_ICONS.get(alert.kind, "⚠️")
    suffix = "\n<i>Моніторинг зупинено.</i>" if alert.stopped and alert.kind != "stopped" else ""
    return f"{icon} {escape(alert.message)}{suffix}"


def _ago(seconds: float | None) -> str:
    if seconds is None:
        return "ще не було"
    if seconds < 90:
        return f"{int(seconds)} с тому"
    if seconds < 3600 * 2:
        return f"{int(seconds // 60)} хв тому"
    return f"{seconds / 3600:.1f} год тому"


def format_status(state: MonitorState, stats: dict[str, int], keywords: tuple[int, int]) -> str:
    if state.paused:
        mode = "⏸ пауза (команда /resume — продовжити)"
    elif state.extension_running:
        mode = "▶️ працює"
    else:
        mode = "⏹ зупинено в розширенні (кнопка «Старт» у Chrome)"
    include, exclude = keywords
    filter_line = (
        f"{include} шукати / {exclude} виключити" if include else "вимкнено — кожен допис вважається лідом"
    )
    posts_ago = None if state.last_posts_at is None else time.time() - state.last_posts_at
    return "\n".join(
        [
            "📊 <b>Статус</b>",
            f"Моніторинг: {mode}",
            f"Зв'язок із розширенням: {_ago(state.seconds_since_seen())}",
            f"Останні дописи: {_ago(posts_ago)}",
            f"База: {stats['total']} дописів, {stats['leads']} лідів, "
            f"{stats['duplicates']} дублікатів, {stats['groups']} груп",
            f"Ключові слова: {filter_line}",
        ]
    )


HELP_TEXT = "\n".join(
    [
        "<b>Facebook Lead Monitor</b>",
        "Сюди приходять нові ліди з груп Facebook.",
        "",
        "/status — стан моніторингу і статистика",
        "/pause — пауза (розширення перестає відкривати групи)",
        "/resume — продовжити",
    ]
)
