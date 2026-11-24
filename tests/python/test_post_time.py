"""Tests for Facebook timestamp parsing."""

from datetime import UTC, datetime, timedelta

import pytest

from lead_monitor.filters.post_time import describe_age, parse_posted_text

NOW = datetime(2026, 11, 24, 17, 40, tzinfo=UTC)  # Tuesday


@pytest.mark.parametrize(
    ("text", "delta"),
    [
        ("Just now", timedelta(0)),
        ("5m", timedelta(minutes=5)),
        ("5 mins", timedelta(minutes=5)),
        ("4h", timedelta(hours=4)),
        ("4 hrs", timedelta(hours=4)),
        ("4 hours ago", timedelta(hours=4)),
        ("an hour ago", timedelta(hours=1)),
        ("2d", timedelta(days=2)),
        ("5 days ago", timedelta(days=5)),
        ("1w", timedelta(weeks=1)),
        ("4 год", timedelta(hours=4)),
        ("4 ч.", timedelta(hours=4)),
        ("5 дн. назад", timedelta(days=5)),
        ("4 дня назад", timedelta(days=4)),
        ("10 хв тому", timedelta(minutes=10)),
    ],
)
def test_relative(text: str, delta: timedelta) -> None:
    assert parse_posted_text(text, NOW) == NOW - delta


def test_yesterday_today_weekday() -> None:
    assert parse_posted_text("Yesterday at 10:15", NOW) == datetime(2026, 11, 23, 10, 15, tzinfo=UTC)
    assert parse_posted_text("Вчора о 10:15", NOW) == datetime(2026, 11, 23, 10, 15, tzinfo=UTC)
    assert parse_posted_text("Yesterday at 2:05 PM", NOW) == datetime(2026, 11, 23, 14, 5, tzinfo=UTC)
    assert parse_posted_text("Today at 09:00", NOW) == datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
    assert parse_posted_text("Sunday at 14:00", NOW) == datetime(2026, 11, 22, 14, 0, tzinfo=UTC)
    assert parse_posted_text("Tuesday at 08:00", NOW) == datetime(2026, 11, 17, 8, 0, tzinfo=UTC)


def test_absolute_dates() -> None:
    assert parse_posted_text("21 November at 14:00", NOW) == datetime(2026, 11, 21, 14, 0, tzinfo=UTC)
    assert parse_posted_text("November 21 at 2:00 PM", NOW) == datetime(2026, 11, 21, 14, 0, tzinfo=UTC)
    assert parse_posted_text("21 листопада о 14:00", NOW) == datetime(2026, 11, 21, 14, 0, tzinfo=UTC)
    assert parse_posted_text("3 March 2024", NOW) == datetime(2024, 3, 3, 12, 0, tzinfo=UTC)
    assert parse_posted_text("December 20", NOW) == datetime(2025, 12, 20, 12, 0, tzinfo=UTC)  # last year


@pytest.mark.parametrize("text", [None, "", "Like", "Comment", "Public group", "31 Smarch", "35 November"])
def test_not_a_time(text: str | None) -> None:
    assert parse_posted_text(text, NOW) is None


def test_describe_age() -> None:
    assert describe_age(NOW - timedelta(minutes=5), NOW) == "5 хв тому (24.11 17:35)"
    assert describe_age(NOW - timedelta(hours=4), NOW) == "4 год тому (24.11 13:40)"
    assert describe_age(NOW - timedelta(days=2), NOW) == "2 дн тому (22.11 17:40)"
