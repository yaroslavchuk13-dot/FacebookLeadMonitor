"""Tests for the keyword filter."""

import os
from pathlib import Path

import pytest

from lead_monitor.filters.keywords import KeywordFile, KeywordFilter, parse_keyword_text


def test_whole_words_and_phrases() -> None:
    f = KeywordFilter(["fire stopping", "plumber"], [])
    assert f.match("Any FIRE   STOPPING work?").matched == ["fire stopping"]
    assert f.match("Need a plumber.").is_lead
    assert not f.match("Nice fireplace stopping by").is_lead
    assert not f.match("plumbers wanted").is_lead  # whole word only


def test_prefix_wildcard() -> None:
    f = KeywordFilter(["plumb*"], [])
    for text in ["plumber", "Plumbing job", "need plumb work"]:
        assert f.match(text).is_lead, text
    assert not f.match("aplumber").is_lead


def test_cyrillic_and_apostrophes() -> None:
    f = KeywordFilter(["сантехнік*", "м'який"], [])
    assert f.match("Шукаю САНТЕХНІКА").is_lead
    assert f.match("потрібен м’який матеріал").is_lead  # typographic apostrophe


def test_exclude_wins() -> None:
    f = KeywordFilter(["fire stopping"], ["we are hiring"])
    result = f.match("We are hiring fire stopping operatives")
    assert not result.is_lead
    assert result.matched == ["fire stopping"]
    assert result.excluded_by == ["we are hiring"]


def test_empty_include_means_every_post_is_a_lead() -> None:
    f = KeywordFilter([], ["spam"])
    assert not f.enabled
    assert f.match("anything").is_lead
    assert not f.match("pure spam").is_lead


def test_parse_file_format() -> None:
    f = parse_keyword_text(
        "# comment\n\n[include]\nfire stopping\n  plumb*  \n[EXCLUDE]\nwe are hiring\n"
        "[location]\nlondon\n"
    )
    assert f.groups == {"include": ["fire stopping", "plumb*"], "location": ["london"]}
    assert f.exclude == ["we are hiring"]


# --- groups: every group must match --------------------------------------------------------

GROUPS_FILE = """
[trade]
fire stop*
fire door*
[offer]
required
looking for a
[location]
london
greenwich
re:\\b(?:se|sw|ec|wc|e|n|nw|w)\\d{1,2}[a-z]?\\b
[exclude]
looking for work
"""


def test_all_groups_must_match() -> None:
    f = parse_keyword_text(GROUPS_FILE)
    ok = f.match("CSCS Fire Stopper required tomorrow in Greenwich £27.50 per hour")
    assert ok.is_lead
    assert ok.matched == ["fire stop*", "required", "greenwich"]

    no_location = f.match("Fire Door Installers required on site in Watford, WD24")
    assert not no_location.is_lead
    assert no_location.missing_groups == ["location"]

    no_offer = f.match("Fire stopping in London is hard")
    assert not no_offer.is_lead and no_offer.missing_groups == ["offer"]


def test_regex_terms_for_postcodes() -> None:
    f = parse_keyword_text(GROUPS_FILE)
    assert f.match("Fire stopper required, site SE10 0AA").is_lead
    assert f.match("fire stopper required in EC2A").is_lead
    assert not f.match("fire stopper required in WD24").is_lead


def test_exclude_beats_groups() -> None:
    f = parse_keyword_text(GROUPS_FILE)
    result = f.match("Team of 3 Fire Stoppers looking for work in London, required asap")
    assert not result.is_lead and result.excluded_by == ["looking for work"]


def test_invalid_regex_is_ignored() -> None:
    f = parse_keyword_text("[location]\nre:(unclosed\nlondon\n")
    assert f.groups == {"location": ["london"]}


def test_lines_outside_sections_are_ignored() -> None:
    assert parse_keyword_text("orphan\n[include]\nok\n").include == ["ok"]


def test_blank_terms_are_dropped() -> None:
    assert KeywordFilter(["", "  ", "*"], []).include == []


def test_keyword_file_reloads_on_change(tmp_path: Path) -> None:
    path = tmp_path / "keywords.txt"
    path.write_text("[include]\nplumber\n", encoding="utf-8")
    kf = KeywordFile(path)
    assert kf.get().include == ["plumber"]

    path.write_text("[include]\nelectrician\n", encoding="utf-8")
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 5))  # make sure mtime differs
    assert kf.get().include == ["electrician"]


def test_missing_keyword_file_disables_filter(tmp_path: Path) -> None:
    kf = KeywordFile(tmp_path / "nope.txt")
    assert not kf.get().enabled


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_with_include_is_not_a_lead(text: str) -> None:
    assert not KeywordFilter(["plumber"], []).match(text).is_lead


def test_keyword_file_with_bom(tmp_path: Path) -> None:
    """Visual Studio and PowerShell often save UTF-8 files with a BOM."""
    path = tmp_path / "keywords.txt"
    path.write_bytes("﻿[include]\nfire stop*\n".encode())
    assert KeywordFile(path).get().include == ["fire stop*"]


def test_found_in_group_returns_words_as_written() -> None:
    f = parse_keyword_text(GROUPS_FILE)
    text = "Fire stopper required in GREENWICH, site SE10 0AA, Greenwich peninsula"
    assert f.found_in_group(text, "location") == ["GREENWICH", "SE10"]
    assert f.found_in_group(text, "nope") == []
