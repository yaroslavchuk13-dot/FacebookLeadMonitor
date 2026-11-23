"""Checks the real config/keywords.txt against real-life examples (fire stopping jobs in London)."""

import pytest

from lead_monitor.core.config import BASE_DIR
from lead_monitor.filters.keywords import parse_keyword_text

FILTER = parse_keyword_text((BASE_DIR / "config" / "keywords.txt").read_text(encoding="utf-8-sig"))

LEADS = [
    "CSCS Fire Stopper required tomorrow in Greenwich\n£27.50 per hour\nMust own own tools & cscs\n"
    "If you can start please call Keano 07545 209 197",
    "Apex Resources LTD is looking for a fire stopper in MOORGATE\n9hrs paid\nContract rate £25/h\n"
    "CSCS card is needed, PPE, TOOLS\nIf available call Jake on +44 7345 405556",
    "Need a fire stopper in Croydon, £200 a day, start Monday",
    "We're hiring passive fire operatives for a site in SE10, immediate start",
    "2 x firestoppers wanted, Canary Wharf, CIS £220/day",
]

NOT_LEADS = [
    # outside London
    "Linsco Recruitment\nFire Door Installers required on site in Watford, WD24\n"
    "Blue CSCS Card, DBS and Asbestos required\nAt least 1 months\n£250 per day",
    "4x Fire Door Carpenters\nPO21-Portsmouth\nBlue CSCS\ndbs enhanced\nrate negotiable doe\nStart asap",
    # workers looking for a job
    "Team of 3 Firestoppers Looking for Work ASAP\nCIS / Contract – Open to discuss\n"
    "We are based in Coventry and travel together in one car",
    "Fire stopper looking for work in London, own tools and CSCS",
    "Anyone need a fire stopper in London? Available from Monday",
    "Any fire stopping work available in the midlands or surrounding areas 2 blue cscs fire stoppers",
    # not a job post
    "Let's welcome our new members to the group! Sean, Ihor, Julius",
    "DBS FIRE IS POORLY TODAY! One of them days where the body says NO",
    "Get your CSCS card fast — CSCS course in London, get registered today, £150",
]


@pytest.mark.parametrize("text", LEADS)
def test_job_offers_in_london_are_leads(text: str) -> None:
    result = FILTER.match(text)
    assert result.is_lead, f"missing groups: {result.missing_groups}, excluded by: {result.excluded_by}"


@pytest.mark.parametrize("text", NOT_LEADS)
def test_other_posts_are_not_leads(text: str) -> None:
    assert not FILTER.match(text).is_lead
