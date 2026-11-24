"""Tests for the post processing pipeline."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from lead_monitor.core.models import FacebookPost
from lead_monitor.filters.keywords import KeywordFile
from lead_monitor.pipeline import PostProcessor
from lead_monitor.storage.database import Database, StoredPost


def make_post(n: int, text: str, author: str = "a") -> FacebookPost:
    return FacebookPost(
        group_id="g1",
        post_url=f"https://www.facebook.com/groups/g1/posts/{n}/",
        author_name=author,
        author_profile_url=f"https://www.facebook.com/{author}",
        text=text,
    )


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[PostProcessor, list[StoredPost], Path]]:
    keywords_path = tmp_path / "keywords.txt"
    keywords_path.write_text("[include]\nplumber\n[exclude]\nwe are hiring\n", encoding="utf-8")
    db = Database(tmp_path / "monitor.db")
    leads: list[StoredPost] = []

    async def collect(lead: StoredPost) -> None:
        leads.append(lead)

    yield PostProcessor(db, KeywordFile(keywords_path), [collect]), leads, keywords_path
    db.close()


def test_only_new_matching_posts_become_leads(setup) -> None:
    processor, leads, _ = setup
    posts = [
        make_post(1, "Need a plumber today"),
        make_post(2, "Selling a sofa"),
        make_post(3, "We are hiring a plumber"),
    ]
    new = asyncio.run(processor.handle_posts(posts))
    assert len(new) == 3
    assert [lead.post.post_url.split("/")[-2] for lead in leads] == ["1"]

    # The same batch again (next monitor cycle): nothing new, no repeated notifications.
    assert asyncio.run(processor.handle_posts(posts)) == []
    assert len(leads) == 1


def test_cross_post_does_not_notify_twice(setup) -> None:
    processor, leads, _ = setup
    asyncio.run(processor.handle_posts([make_post(1, "Need a plumber")]))
    asyncio.run(processor.handle_posts([make_post(2, "Need a  PLUMBER")]))
    assert len(leads) == 1


def test_failing_handler_does_not_break_others(tmp_path: Path) -> None:
    db = Database(tmp_path / "monitor.db")
    calls: list[int] = []

    async def broken(lead: StoredPost) -> None:
        raise RuntimeError("telegram is down")

    async def working(lead: StoredPost) -> None:
        calls.append(lead.id)

    processor = PostProcessor(db, KeywordFile(tmp_path / "missing.txt"), [broken, working])
    asyncio.run(processor.handle_posts([make_post(1, "anything")]))
    assert len(calls) == 1  # empty keyword file -> every post is a lead
    db.close()


# --- post date and age limit ---------------------------------------------------------------


def dated_post(n: int, posted_text: str | None) -> FacebookPost:
    return FacebookPost(
        group_id="g1",
        post_url=f"https://www.facebook.com/groups/g1/posts/{n}/",
        author_name=f"a{n}",
        author_profile_url=f"https://www.facebook.com/a{n}",
        text=f"Need a plumber {n}",
        posted_text=posted_text,
    )


def test_old_posts_are_saved_but_not_leads(tmp_path: Path) -> None:
    keywords_path = tmp_path / "keywords.txt"
    keywords_path.write_text("[include]\nplumber\n", encoding="utf-8")
    db = Database(tmp_path / "monitor.db")
    leads: list[StoredPost] = []

    async def collect(lead: StoredPost) -> None:
        leads.append(lead)

    processor = PostProcessor(db, KeywordFile(keywords_path), [collect], max_age_hours=24)
    new = asyncio.run(processor.handle_posts([
        dated_post(1, "3h"),            # fresh -> lead
        dated_post(2, "5 days ago"),    # too old -> saved, not a lead
        dated_post(3, None),            # unknown date -> lead (better not to miss)
        dated_post(4, "gibberish"),     # not understood -> lead
    ]))
    assert len(new) == 4
    assert sorted(lead.id for lead in leads) == [1, 3, 4]
    row = db.get_lead(1)
    assert row["posted_at"] is not None  # parsed date is stored
    db.close()
