"""Scam check workflow.

1. New lead -> signs from the post text and author name are computed at once.
2. Anonymous author -> verdict right away. Author checked recently -> cached profile signs.
3. Otherwise a profile check is queued; the extension opens the profile on its next cycle
   and sends back numbers/flags (POST /api/profile_result).
4. Verdict is saved and handlers are notified (Telegram edits the lead message).
5. Checks not done within check_timeout_minutes get a verdict without the profile.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from lead_monitor.core.models import ScamLevel
from lead_monitor.scam.rules import (
    ProfileSignals,
    ScamRules,
    Signs,
    author_signs,
    profile_signs,
    text_signs,
    verdict,
)
from lead_monitor.storage.database import Database, StoredPost

log = logging.getLogger(__name__)

VerdictHandler = Callable[[int], Awaitable[None]]

NOTE_PREFIX = "ℹ️ "  # informational line stored with red signs, shown as is, not counted
NOTE_PROFILE_NOT_CHECKED = NOTE_PREFIX + "Профіль автора не перевірено"
NOTE_PROFILE_FAILED = NOTE_PREFIX + "Профіль автора не вдалося відкрити"
EXPIRY_CHECK_SECONDS = 5 * 60


class ScamChecker:
    def __init__(
        self,
        database: Database,
        rules: ScamRules,
        verdict_handlers: list[VerdictHandler] | None = None,
    ) -> None:
        self.database = database
        self.rules = rules
        self.verdict_handlers = verdict_handlers if verdict_handlers is not None else []

    # --- pipeline -----------------------------------------------------------------------------

    async def on_new_lead(self, lead: StoredPost) -> None:
        """Lead handler: must run before the Telegram notifier, so a ready verdict is sent at once."""
        post = lead.post
        base = self._base_signs(post.text, post.author_name, post.author_profile_url)
        if not post.author_profile_url:
            await self._finish(lead.id, base, profile_checked=False)
            return
        cached = await asyncio.to_thread(
            self.database.get_author_profile, post.author_profile_url, self.rules.cache_days
        )
        if cached is not None:
            await self._finish(lead.id, base + Signs(cached["red"], cached["green"]), profile_checked=True)
            return
        await asyncio.to_thread(
            self.database.set_scam_result, lead.id, ScamLevel.PENDING.value, base.red, base.green
        )
        await asyncio.to_thread(self.database.add_profile_check, lead.id, post.author_profile_url)
        log.info("Lead #%d: author profile queued for the scam check", lead.id)

    # --- extension ------------------------------------------------------------------------------

    async def next_task(self) -> dict[str, Any] | None:
        """The next profile for the extension to open: {"id", "profile_url"} or None."""
        check = await asyncio.to_thread(self.database.next_profile_check)
        return {"id": check["id"], "profile_url": check["profile_url"]} if check else None

    async def complete(self, check_id: int, profile: ProfileSignals) -> bool:
        """Result from the extension. Returns False for an unknown or already closed check."""
        check = await asyncio.to_thread(self.database.get_profile_check, check_id)
        if check is None or check["status"] != "pending":
            return False
        url = check["profile_url"]
        if profile.status == "error":
            post_ids = await asyncio.to_thread(self.database.finish_profile_checks, url, "failed")
            for post_id in post_ids:
                await self._finish_from_db(post_id, Signs(red=[NOTE_PROFILE_FAILED]), profile_checked=False)
            return True

        signs = profile_signs(profile, self.rules)
        await asyncio.to_thread(self.database.save_author_profile, url, signs.red, signs.green)
        post_ids = await asyncio.to_thread(self.database.finish_profile_checks, url, "done")
        for post_id in post_ids:
            await self._finish_from_db(post_id, signs, profile_checked=True)
        log.info("Profile check #%d done for %d lead(s)", check_id, len(post_ids))
        return True

    async def expire(self) -> int:
        post_ids = await asyncio.to_thread(
            self.database.expire_profile_checks, self.rules.check_timeout_minutes
        )
        for post_id in post_ids:
            await self._finish_from_db(post_id, Signs(red=[NOTE_PROFILE_NOT_CHECKED]), profile_checked=False)
        if post_ids:
            log.info("%d profile check(s) expired — verdict without the profile", len(post_ids))
        return len(post_ids)

    async def run_expiry(self) -> None:
        while True:
            await self.expire()
            await asyncio.sleep(EXPIRY_CHECK_SECONDS)

    # --- verdict ---------------------------------------------------------------------------------

    def _base_signs(self, text: str, author_name: str | None, profile_url: str | None) -> Signs:
        return text_signs(text, self.rules) + author_signs(author_name, profile_url)

    async def _finish_from_db(self, post_id: int, extra: Signs, profile_checked: bool) -> None:
        lead = await asyncio.to_thread(self.database.get_lead, post_id)
        if lead is None:
            return
        base = self._base_signs(lead["text"], lead["author_name"], lead["author_profile_url"])
        await self._finish(post_id, base + extra, profile_checked)

    async def _finish(self, post_id: int, signs: Signs, profile_checked: bool) -> None:
        counted = Signs([s for s in signs.red if not s.startswith(NOTE_PREFIX)], signs.green)
        level = verdict(counted, self.rules, profile_checked)
        await asyncio.to_thread(self.database.set_scam_result, post_id, level.value, signs.red, signs.green)
        log.info("Lead #%d: scam check %s %s", post_id, level.emoji, "; ".join(signs.red) or "no red signs")
        for handler in self.verdict_handlers:
            try:
                await handler(post_id)
            except Exception:
                log.exception("Verdict handler failed for lead #%d", post_id)
