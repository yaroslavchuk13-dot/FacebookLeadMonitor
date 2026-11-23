"""Scam rules: pure functions that turn a post / profile into red and green signs.

Only verdicts and short human-readable signs are produced — no photos, no profile text.
"""

import re
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lead_monitor.core.models import ScamLevel
from lead_monitor.filters.pay import extract_pay

VOWELS = set("aeiouyаеєиіїоуюяёэы")


@dataclass(frozen=True)
class ScamRules:
    red_for_scam: int = 2
    max_realistic_hourly: float = 45
    max_realistic_daily: float = 400
    min_friends: int = 20
    good_friends: int = 100
    new_account_years: int = 1
    old_account_years: int = 3
    cache_days: int = 7
    check_timeout_minutes: int = 60
    prepayment: tuple[str, ...] = ("upfront", "deposit", "admin fee", "registration fee", "передоплат")
    messenger_only: tuple[str, ...] = ("only whatsapp", "whatsapp only", "only telegram", "telegram only")
    crypto: tuple[str, ...] = ("crypto", "bitcoin", "usdt", "binance")

    @classmethod
    def load(cls, path: Path) -> "ScamRules":
        """Reads config/scam_rules.toml; missing file or keys -> defaults."""
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        flat: dict[str, object] = {}
        for section in data.values():
            if isinstance(section, dict):
                flat.update(section)
        known = {k: (tuple(v) if isinstance(v, list) else v) for k, v in flat.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Signs:
    red: list[str] = field(default_factory=list)
    green: list[str] = field(default_factory=list)

    def __add__(self, other: "Signs") -> "Signs":
        return Signs(self.red + other.red, self.green + other.green)


class ProfileSignals(BaseModel):
    """What the extension reads from the author's profile page (numbers and flags only)."""

    model_config = ConfigDict(extra="ignore")

    status: str = "ok"  # ok | unavailable | error
    has_photo: bool | None = None
    friends: int | None = None
    followers: int | None = None
    joined_year: int | None = None
    intro_items: int | None = None  # "Lives in", "Works at", ... lines in the Intro
    is_locked: bool = False
    is_page: bool = False  # a business Page, not a person


# --- text of the post ---------------------------------------------------------------------


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase.lower() in text for phrase in phrases)


def text_signs(text: str, rules: ScamRules) -> Signs:
    signs = Signs()
    lowered = text.lower()
    if _contains(lowered, rules.prepayment):
        signs.red.append("Просять передоплату / внесок")
    if _contains(lowered, rules.messenger_only):
        signs.red.append("Зв'язок лише через WhatsApp/Telegram")
    if _contains(lowered, rules.crypto):
        signs.red.append("Згадується криптовалюта")

    pays = extract_pay(text)
    unrealistic = [
        p for p in pays
        if (p.unit == "hour" and (p.amount_to or p.amount) > rules.max_realistic_hourly)
        or (p.unit == "day" and (p.amount_to or p.amount) > rules.max_realistic_daily)
    ]
    if unrealistic:
        signs.red.append(f"Нереально висока оплата ({unrealistic[0].label()})")
    elif any(p.unit in ("hour", "day") for p in pays):
        signs.green.append("Реалістична оплата вказана")
    return signs


def name_looks_generated(name: str | None) -> bool:
    """Digits in the name, a long word without vowels, or random letter casing (e.g. "jOhNsmItH")."""
    if not name:
        return False
    if any(ch.isdigit() for ch in name):
        return True
    for word in re.findall(r"[^\W\d_]+", name):
        if len(word) >= 5 and not (set(word.lower()) & VOWELS):
            return True
        if len(word) >= 4 and not word.isupper() and sum(ch.isupper() for ch in word[1:]) >= 2:
            return True
    return False


def author_signs(author_name: str | None, profile_url: str | None) -> Signs:
    signs = Signs()
    if not profile_url:
        signs.red.append("Анонімний допис (автор прихований)")
    if name_looks_generated(author_name):
        signs.red.append("Ім'я схоже на згенероване")
    return signs


# --- author's profile ---------------------------------------------------------------------


def profile_signs(profile: ProfileSignals, rules: ScamRules, now_year: int | None = None) -> Signs:
    signs = Signs()
    if profile.status == "unavailable":
        signs.red.append("Профіль недоступний або видалений")
        return signs
    if profile.status != "ok":
        return signs
    if profile.is_page:
        signs.green.append("Бізнес-сторінка (компанія)")
        return signs

    if profile.has_photo is False:
        signs.red.append("Немає фото профілю")
    elif profile.has_photo:
        signs.green.append("Є фото профілю")

    year = now_year or datetime.now(UTC).year
    if profile.joined_year is not None:
        age = year - profile.joined_year
        if age < rules.new_account_years:
            signs.red.append(f"Новий акаунт (з {profile.joined_year} р.)")
        elif age >= rules.old_account_years:
            signs.green.append(f"Акаунт з {profile.joined_year} р.")

    if profile.friends is not None:
        if profile.friends < rules.min_friends:
            signs.red.append(f"Мало друзів ({profile.friends})")
        elif profile.friends >= rules.good_friends:
            signs.green.append(f"Багато друзів ({profile.friends})")

    if profile.intro_items is not None and not profile.is_locked:
        if profile.intro_items == 0:
            signs.red.append("Порожній профіль (немає інформації)")
        elif profile.intro_items >= 2:
            signs.green.append("Заповнена інформація в профілі")
    return signs


# --- verdict ------------------------------------------------------------------------------------

# Criteria that can give a sign; "most green" is counted against this number.
TOTAL_CRITERIA = 6


def verdict(signs: Signs, rules: ScamRules, profile_checked: bool) -> ScamLevel:
    if len(signs.red) >= rules.red_for_scam:
        return ScamLevel.RED
    if signs.red:
        return ScamLevel.YELLOW
    if profile_checked and len(signs.green) * 2 > TOTAL_CRITERIA:
        return ScamLevel.GREEN
    return ScamLevel.YELLOW  # mixed or too little data
