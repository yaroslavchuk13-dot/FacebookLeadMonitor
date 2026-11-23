"""Tests for the SQLite storage."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from lead_monitor.core.models import FacebookPost
from lead_monitor.filters.keywords import KeywordMatch
from lead_monitor.storage.database import MIGRATIONS, Database, content_hash

LEAD = KeywordMatch(is_lead=True, matched=["plumber"])
NOT_LEAD = KeywordMatch(is_lead=False)


def make_post(n: int = 1, **overrides: object) -> FacebookPost:
    data: dict[str, object] = {
        "group_id": "g1",
        "group_name": "Group 1",
        "post_url": f"https://www.facebook.com/groups/g1/posts/{n}/",
        "author_name": "Ivan",
        "author_profile_url": "https://www.facebook.com/profile.php?id=7",
        "text": f"Need a plumber #{n}",
    }
    data.update(overrides)
    return FacebookPost(**data)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "sub" / "monitor.db")
    yield database
    database.close()


def test_schema_created(db: Database) -> None:
    assert db.path.exists()
    assert db.schema_version == len(MIGRATIONS)
    assert db.stats() == {"total": 0, "leads": 0, "duplicates": 0, "groups": 0}


def test_new_post_saved(db: Database) -> None:
    stored = db.add_post(make_post(), LEAD)
    assert stored is not None
    assert stored.is_lead and not stored.is_duplicate
    assert stored.matched_keywords == ["plumber"]
    assert db.stats()["total"] == 1


def test_same_url_saved_once(db: Database) -> None:
    assert db.add_post(make_post(1), LEAD) is not None
    assert db.add_post(make_post(1), LEAD) is None
    assert db.stats()["total"] == 1


def test_cross_post_is_duplicate_and_not_a_lead(db: Database) -> None:
    db.add_post(make_post(1, text="Need a plumber"), LEAD)
    other_group = make_post(
        2, group_id="g2", post_url="https://www.facebook.com/groups/g2/posts/2/",
        text="  NEED a   plumber ",
    )
    stored = db.add_post(other_group, LEAD)
    assert stored is not None
    assert stored.is_duplicate and not stored.is_lead
    assert db.stats() == {"total": 2, "leads": 1, "duplicates": 1, "groups": 2}


def test_same_text_from_other_author_is_not_duplicate(db: Database) -> None:
    db.add_post(make_post(1, text="Need a plumber"), LEAD)
    stored = db.add_post(
        make_post(2, text="Need a plumber", author_profile_url="https://www.facebook.com/someone"),
        LEAD,
    )
    assert stored is not None and stored.is_lead and not stored.is_duplicate


def test_not_matching_post_is_saved_but_not_a_lead(db: Database) -> None:
    stored = db.add_post(make_post(), NOT_LEAD)
    assert stored is not None and not stored.is_lead
    assert db.recent_leads() == []


def test_recent_leads_newest_first(db: Database) -> None:
    for n in range(1, 4):
        db.add_post(make_post(n), LEAD)
    leads = db.recent_leads(limit=2)
    assert [lead["post_url"].split("/")[-2] for lead in leads] == ["3", "2"]
    assert leads[0]["matched_keywords"] == ["plumber"]


def test_data_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "monitor.db"
    first = Database(path)
    first.add_post(make_post(), LEAD)
    first.close()
    second = Database(path)  # migrations must not run again or wipe data
    assert second.stats()["total"] == 1
    assert second.add_post(make_post(), LEAD) is None
    second.close()


def test_content_hash_ignores_case_and_spacing() -> None:
    assert content_hash(make_post(text="Need  a\nPlumber")) == content_hash(make_post(text="need a plumber"))
    assert content_hash(make_post(text="a")) != content_hash(make_post(text="b"))
