"""Telegram message texts (HTML parse mode). Pure functions, unit-tested."""

import time
from datetime import datetime
from html import escape
from typing import Any

from lead_monitor.core.models import ExtensionAlert
from lead_monitor.core.state import MonitorState
from lead_monitor.filters.job_details import extract_details
from lead_monitor.filters.pay import describe_pay
from lead_monitor.filters.post_time import describe_age

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


MAX_TITLE_CHARS = 90
SHORT_FIRST_LINE = 20  # "Linsco Recruitment" alone is not a title: add the next line


def lead_title(text: str) -> str:
    """The job title: the first line of the post (plus the second one if the first is short)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "Вакансія"
    title = lines[0]
    if len(title) < SHORT_FIRST_LINE and len(lines) > 1:
        title = f"{title} — {lines[1]}"
    return title if len(title) <= MAX_TITLE_CHARS else title[:MAX_TITLE_CHARS].rstrip() + "…"


def _posted(lead: dict[str, Any], now: datetime | None) -> str:
    raw = lead.get("posted_at")
    if not raw:
        return "Дата допису невідома"
    try:
        posted_at = datetime.fromisoformat(raw)
    except ValueError:
        return "Дата допису невідома"
    now = now or datetime.now().astimezone()
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=now.tzinfo)
    return describe_age(posted_at, now)


def format_lead(lead: dict[str, Any], location: list[str] | None = None, now: datetime | None = None) -> str:
    """Lead message: title, then separate lines for pay, place, date, group, author, scam check,
    and the full post text in a collapsible quote."""
    group = escape(lead.get("group_name") or lead["group_id"])
    author = escape(lead.get("author_name") or "Анонімно")
    profile = lead.get("author_profile_url")
    author_value = f'<a href="{escape(profile, quote=True)}">{author}</a>' if profile else author

    text = lead["text"]
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rstrip() + "…"

    title = lead_title(lead["text"])
    details = extract_details(lead["text"], title=title)
    lines = [
        f"🕒 <b>{escape(_posted(lead, now))}</b>",
        f"🔥 <b>{escape(title)}</b>",
        "",
        f"💷 <b>Оплата:</b> {escape(describe_pay(lead['text']))}",
        f"📍 <b>Місце:</b> {escape(', '.join(location)) if location else 'не вказано'}",
    ]
    if details.requirements:
        lines += ["", "📋 <b>Вимоги:</b>", *[f"• {escape(item)}" for item in details.requirements]]
    if details.info:
        lines += ["", "ℹ️ <b>Додатково:</b>", *[f"• {escape(item)}" for item in details.info]]
    contact = ", ".join(details.contacts) if details.contacts else "не вказано — напишіть автору"
    lines += [
        "",
        f"📞 <b>Контакт:</b> {escape(contact)}",
        f"👤 <b>Автор:</b> {author_value}",
        f"👥 <b>Група:</b> {group}",
    ]
    scam = format_scam(lead)
    if scam:
        lines += ["", *scam]
    lines += ["", f"<blockquote expandable>{escape(text)}</blockquote>"]
    if is_fallback_link(lead["post_url"]):
        lines.append("<i>Посилання на сам допис не знайдено — кнопка відкриє групу.</i>")
    return "\n".join(lines)


MAX_SCAM_REASONS = 4


def format_scam(lead: dict[str, Any]) -> list[str]:
    """Lines about the author check; empty for leads saved before the scam check existed."""
    level = lead.get("scam_level")
    red = lead.get("scam_red") or []
    green = lead.get("scam_green") or []
    if not level:
        return []
    if level == "pending":
        return ["🛡 <i>Перевіряю автора…</i>"]
    reasons_red = [escape(r) if r.startswith("ℹ️") else f"• {escape(r)}" for r in red]
    if len(reasons_red) > MAX_SCAM_REASONS:
        extra = len(reasons_red) - MAX_SCAM_REASONS
        reasons_red = [*reasons_red[:MAX_SCAM_REASONS], f"…і ще {extra}"]
    if level == "red":
        return ["🛡 🔴 <b>Схоже на скам</b>", *reasons_red]
    if level == "green":
        return ["🛡 🟢 Явних ознак скаму не знайдено", *[f"✓ {escape(g)}" for g in green][:MAX_SCAM_REASONS]]
    found_green = [f"✓ {escape(g)}" for g in green][:MAX_SCAM_REASONS]
    if not reasons_red:
        reasons_red = ["• Мало даних про автора"]
    return ["🛡 🟡 <b>Будьте уважні</b>", *reasons_red, *found_green]


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
