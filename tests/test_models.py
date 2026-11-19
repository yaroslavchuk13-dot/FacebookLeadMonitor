"""Tests for core data models."""

import pytest
from pydantic import ValidationError

from models import FacebookPost, ScamCheckResult, ScamLevel

POST_URL = "https://www.facebook.com/groups/123/posts/456/"
PROFILE_URL = "https://www.facebook.com/profile.php?id=789"


def make_post(**overrides: object) -> FacebookPost:
    data: dict[str, object] = {
        "group_id": "123",
        "post_url": POST_URL,
        "author_name": "Ivan",
        "author_profile_url": PROFILE_URL,
        "text": "  Шукаю сантехніка  ",
    }
    data.update(overrides)
    return FacebookPost(**data)


def test_valid_post() -> None:
    post = make_post()
    assert post.text == "Шукаю сантехніка"  # whitespace stripped
    assert post.is_anonymous is False
    assert post.collected_at.tzinfo is not None
    assert post.posted_at is None


def test_anonymous_post() -> None:
    post = make_post(author_name="", author_profile_url=" ")
    assert post.author_name is None
    assert post.is_anonymous is True


def test_extra_fields_ignored() -> None:
    assert not hasattr(make_post(unknown_field="x"), "unknown_field")


@pytest.mark.parametrize(
    "overrides",
    [
        {"text": "   "},
        {"group_id": ""},
        {"post_url": "https://evil.example.com/groups/123/posts/456/"},
        {"post_url": "http://www.facebook.com/groups/123/posts/456/"},
        {"post_url": "https://facebook.com.evil.com/x"},
        {"author_profile_url": "https://example.com/user"},
    ],
)
def test_invalid_post_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_post(**overrides)


def test_post_is_immutable() -> None:
    with pytest.raises(ValidationError):
        make_post().text = "changed"


@pytest.mark.parametrize(
    ("level", "emoji"),
    [(ScamLevel.PENDING, "👤"), (ScamLevel.GREEN, "🟢"), (ScamLevel.YELLOW, "🟡"),
     (ScamLevel.RED, "🔴")],
)
def test_scam_level_emoji(level: ScamLevel, emoji: str) -> None:
    assert level.emoji == emoji


def test_scam_level_from_string() -> None:
    assert ScamLevel("red") is ScamLevel.RED


def test_scam_check_result_defaults() -> None:
    result = ScamCheckResult()
    assert result.level is ScamLevel.PENDING
    assert result.red_flags == [] and result.green_flags == []


def test_scam_check_result_has_no_personal_data_fields() -> None:
    assert set(ScamCheckResult.model_fields) == {"level", "red_flags", "green_flags", "checked_at"}
