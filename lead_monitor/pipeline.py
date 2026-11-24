"""Post processing pipeline: post date -> keywords -> age limit -> database (dedup) -> lead handlers.

Lead handlers are async callbacks called for every new lead (log, scam check, Telegram).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from lead_monitor.core.models import FacebookPost
from lead_monitor.filters.keywords import KeywordFile, KeywordMatch
from lead_monitor.filters.post_time import parse_posted_text
from lead_monitor.storage.database import Database, StoredPost

log = logging.getLogger(__name__)

LeadHandler = Callable[[StoredPost], Awaitable[None]]


async def log_lead(lead: StoredPost) -> None:
    post = lead.post
    keywords = ", ".join(lead.matched_keywords) or "(фільтр вимкнено)"
    preview = post.text[:100].replace("\n", " ")
    log.info(
        "LEAD #%d | %s | %s | keywords: %s | %s | %s",
        lead.id, post.group_name or post.group_id, post.author_name or "(анонімно)",
        keywords, post.post_url, preview,
    )


class PostProcessor:
    def __init__(
        self,
        database: Database,
        keywords: KeywordFile,
        lead_handlers: list[LeadHandler] | None = None,
        max_age_hours: float | None = None,
    ) -> None:
        self.database = database
        self.keywords = keywords
        self.lead_handlers = lead_handlers if lead_handlers is not None else [log_lead]
        self.max_age_hours = max_age_hours

    async def handle_posts(self, posts: list[FacebookPost]) -> list[StoredPost]:
        """Saves new posts and calls lead handlers for new leads. Returns the new posts."""
        keyword_filter = self.keywords.get()
        now = datetime.now().astimezone()
        new_posts: list[StoredPost] = []
        too_old = 0
        for post in posts:
            if post.posted_at is None and post.posted_text:
                posted_at = parse_posted_text(post.posted_text, now)
                if posted_at is not None:
                    post = post.model_copy(update={"posted_at": posted_at})
            match = keyword_filter.match(post.text)
            if match.is_lead and self._is_too_old(post, now):
                # Old post seen for the first time (e.g. deeper scrolling): keep it, do not notify.
                match = KeywordMatch(is_lead=False, matched=match.matched)
                too_old += 1
            stored = await asyncio.to_thread(self.database.add_post, post, match)
            if stored is not None:
                new_posts.append(stored)

        leads = [p for p in new_posts if p.is_lead]
        if new_posts:
            log.info(
                "Saved %d new posts (%d leads, %d duplicates, %d too old to notify), %d already known",
                len(new_posts), len(leads), sum(p.is_duplicate for p in new_posts), too_old,
                len(posts) - len(new_posts),
            )
        for lead in leads:
            for handler in self.lead_handlers:
                try:
                    await handler(lead)
                except Exception:  # one failing handler must not lose the others
                    log.exception("Lead handler %s failed for lead #%d", handler.__name__, lead.id)
        return new_posts

    def _is_too_old(self, post: FacebookPost, now: datetime) -> bool:
        if self.max_age_hours is None or post.posted_at is None:
            return False  # unknown date: better to notify than to miss a job
        return now - post.posted_at > timedelta(hours=self.max_age_hours)
