"""Tests for splitting a job post into requirements / info / contacts."""

from lead_monitor.filters.job_details import extract_details, find_contacts

MKA = """MKA require 2 fire stoppers for a project in Greenwich.
Start date - ASAP.
Duration - 5 weeks.
Hours - 8am -4pm.
Duties - Batt and mastic work in high rise flats.
Applicants must have own vehicle - parking permit will be provided.
Requirements - LVL2 Passive fire protection ideally.
If available and interested then please contact MKA immediately on 01708 206540 but please email your ECS card, CV and references in the meantime to jobs@mka-ltd.com"""

LEWIS = """CSCS Fire Stopper required tomorrow in Greenwich
£27.50 per hour
Must own own tools & cscs
If you can start please call Keano 07545 209 197"""

APEX = """Apex Resources LTD is looking for a fire stopper in MOORGATE
9hrs paid
Contract rate £25/h
CSCS card is needed, PPE, TOOLS
If available call Jake on +44 7345 405556"""


def test_mka_post() -> None:
    d = extract_details(MKA, title="MKA require 2 fire stoppers for a project in Greenwich.")
    assert d.requirements == [
        "Applicants must have own vehicle - parking permit will be provided",
        "LVL2 Passive fire protection ideally",
    ]
    assert d.info == ["Start date - ASAP", "Duration - 5 weeks", "Hours - 8am -4pm", "Batt and mastic work in high rise flats"]
    assert d.contacts == ["01708 206540", "jobs@mka-ltd.com"]


def test_lewis_post() -> None:
    d = extract_details(LEWIS, title="CSCS Fire Stopper required tomorrow in Greenwich")
    assert d.requirements == ["Must own own tools & cscs"]
    assert d.contacts == ["07545 209 197"]
    assert "£27.50 per hour" not in d.info + d.requirements  # shown in the pay block


def test_apex_post() -> None:
    d = extract_details(APEX, title="Apex Resources LTD is looking for a fire stopper in MOORGATE")
    assert d.requirements == ["CSCS card is needed, PPE, TOOLS"]
    assert d.info == ["9hrs paid"]
    assert d.contacts == ["+44 7345 405556"]


def test_contacts_without_phone() -> None:
    assert find_contacts("Fire stoppers needed, DM me for details") == ["DM (у дописі)"]
    assert find_contacts("Fire stoppers needed in London") == []


def test_pay_and_postcodes_are_not_phones() -> None:
    assert find_contacts("£250 per day, site SE10 0AA, 2025 start, 9hrs") == []
