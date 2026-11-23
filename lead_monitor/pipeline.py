"""Post processing pipeline: keywords -> database (deduplication) -> lead handlers.

Lead handlers are async callbacks called for every new lead. M3 adds the Telegram
notifier as a handler; until then leads are written to the log.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from lead_monitor.core.models import FacebookPost
from lead_monitor.filters.keywords import KeywordFile
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
    ) -> None:
        self.database = database
        self.keywords = keywords
        self.lead_handlers = lead_handlers if lead_handlers is not None else [log_lead]

    async def handle_posts(self, posts: list[FacebookPost]) -> list[StoredPost]:
        """Saves new posts and calls lead handlers for new leads. Returns the new posts."""
        keyword_filter = self.keywords.get()
        new_posts: list[StoredPost] = []
        for post in posts:
            match = keyword_filter.match(post.text)
            stored = await asyncio.to_thread(self.database.add_post, post, match)
            if stored is not None:
                new_posts.append(stored)

        leads = [p for p in new_posts if p.is_lead]
        if new_posts:
            log.info(
                "Saved %d new posts (%d leads, %d duplicates), %d already known",
                len(new_posts), len(leads), sum(p.is_duplicate for p in new_posts),
                len(posts) - len(new_posts),
            )
        for lead in leads:
            for handler in self.lead_handlers:
                try:
                    await handler(lead)
                except Exception:  # one failing handler must not lose the others
                    log.exception("Lead handler %s failed for lead #%d", handler.__name__, lead.id)
        return new_posts
