"""Tests for pay extraction from job posts."""

import pytest

from lead_monitor.filters.pay import describe_pay, extract_pay, shift_hours


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£27.50 per hour", "£27.50/год (≈ £220 за 8-год день)"),
        ("9hrs paid\nContract rate £25/h", "£25/год (≈ £225 за 9-год день)"),
        ("Fire Door Installers\n£250 per day", "£250/день"),
        ("£220/day CIS", "£220/день"),
        ("£ 200 a day, start Monday", "£200/день"),
        ("rate £25-£28 ph", "£25–£28/год (≈ £200–£224 за 8-год день)"),
        ("Price work £12 per m2", "£12/м²"),
        ("Pay: £1000 per week", "£1000/тиждень"),
        ("rate negotiable doe", "не вказана"),
        ("27.50 per hour, 10 hour days", "£27.50/год (≈ £275 за 10-год день)"),
        ("Pay rate £180", "£180"),
    ],
)
def test_describe_pay(text: str, expected: str) -> None:
    assert describe_pay(text) == expected


def test_phone_numbers_and_postcodes_are_not_pay() -> None:
    text = "Call Keano 07545 209 197, site SE10 0AA, 3 x Blue CSCS, 2+ years"
    assert extract_pay(text) == []


def test_several_rates() -> None:
    pays = extract_pay("Fire stoppers £25ph, supervisors £280 per day")
    assert [p.label() for p in pays] == ["£25/год", "£280/день"]
    # hourly + daily given -> no day estimate
    assert describe_pay("Fire stoppers £25ph, supervisors £280 per day") == "£25/год, £280/день"


def test_shift_hours() -> None:
    assert shift_hours("9hrs paid") == 9
    assert shift_hours("8 hours shifts") == 8
    assert shift_hours("2 hours notice") is None
    assert shift_hours("3 hours away") is None
    assert shift_hours("nothing") is None
