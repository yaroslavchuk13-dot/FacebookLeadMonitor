"""Tests for scam rules (pure functions)."""

from lead_monitor.core.config import BASE_DIR
from lead_monitor.core.models import ScamLevel
from lead_monitor.scam.rules import (
    ProfileSignals,
    ScamRules,
    Signs,
    author_signs,
    name_looks_generated,
    profile_signs,
    text_signs,
    verdict,
)

RULES = ScamRules.load(BASE_DIR / "config" / "scam_rules.toml")


def test_config_file_loads() -> None:
    assert RULES.red_for_scam == 2
    assert "upfront" in RULES.prepayment
    assert RULES.check_timeout_minutes == 60


def test_missing_config_gives_defaults(tmp_path) -> None:
    assert ScamRules.load(tmp_path / "nope.toml") == ScamRules()


def test_text_red_signs() -> None:
    signs = text_signs(
        "Fire stopper needed £70 per hour! Small upfront fee for CSCS. Contact only on Telegram, paid in USDT",
        RULES,
    )
    assert signs.red == [
        "Просять передоплату / внесок",
        "Зв'язок лише через WhatsApp/Telegram",
        "Згадується криптовалюта",
        "Нереально висока оплата (£70/год)",
    ]


def test_text_normal_job_post() -> None:
    signs = text_signs("CSCS Fire Stopper required tomorrow in Greenwich £27.50 per hour, call Keano", RULES)
    assert signs.red == []
    assert signs.green == ["Реалістична оплата вказана"]


def test_call_or_whatsapp_is_not_a_red_sign() -> None:
    assert text_signs("Call or WhatsApp 07700 900000, £25ph", RULES).red == []


def test_generated_names() -> None:
    for name in ["John Smith88", "Xkrtzv Bmlq", "jOhNsMiTh Lee"]:
        assert name_looks_generated(name), name
    for name in ["Viktor VH", "DBS FIRE LTD", "Nicoleta Silav", "Іван Петренко", "Ó Briain", None]:
        assert not name_looks_generated(name), name


def test_anonymous_author() -> None:
    assert author_signs("Anonymous participant", None).red == ["Анонімний допис (автор прихований)"]
    assert author_signs("Ivan Petrenko", "https://www.facebook.com/ivan").red == []


def test_profile_signs() -> None:
    good = ProfileSignals(has_photo=True, friends=350, joined_year=2014, intro_items=3)
    signs = profile_signs(good, RULES, now_year=2026)
    assert signs.red == []
    assert len(signs.green) == 4

    bad = ProfileSignals(has_photo=False, friends=3, joined_year=2026, intro_items=0)
    assert len(profile_signs(bad, RULES, now_year=2026).red) == 4

    assert profile_signs(ProfileSignals(status="unavailable"), RULES).red == ["Профіль недоступний або видалений"]
    assert profile_signs(ProfileSignals(is_page=True), RULES).green == ["Бізнес-сторінка (компанія)"]
    # locked profile: empty intro is not held against the author
    locked = ProfileSignals(is_locked=True, intro_items=0, has_photo=True)
    assert profile_signs(locked, RULES).red == []


def test_verdict_levels() -> None:
    assert verdict(Signs(red=["a", "b"]), RULES, True) is ScamLevel.RED
    assert verdict(Signs(red=["a"], green=["1", "2", "3", "4"]), RULES, True) is ScamLevel.YELLOW
    assert verdict(Signs(green=["1", "2", "3", "4"]), RULES, True) is ScamLevel.GREEN
    assert verdict(Signs(green=["1", "2"]), RULES, True) is ScamLevel.YELLOW  # too little data
    assert verdict(Signs(green=["1", "2", "3", "4"]), RULES, False) is ScamLevel.YELLOW  # profile not checked
