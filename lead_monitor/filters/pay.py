"""Extracts the pay from a job post: "£27.50 per hour", "£250/day", "Contract rate £25/h"."""

import re
from dataclasses import dataclass

DEFAULT_DAY_HOURS = 8

UNIT_WORDS = {
    "hour": r"(?:per\s*hour|p/?h|/\s*hr?s?|an\s*hour|a\s*hour|hourly|ph|phr|hr|hour)",
    "day": r"(?:per\s*day|p/?d|/\s*day|a\s*day|daily|pd|per\s*shift|/\s*shift|day)",
    "week": r"(?:per\s*week|p/?w|/\s*week|a\s*week|weekly|pw)",
    "m2": r"(?:per\s*(?:m2|m²|sqm|square\s*met(?:re|er))|/\s*(?:m2|m²|sqm))",
}
UNIT_LABELS = {"hour": "год", "day": "день", "week": "тиждень", "m2": "м²"}

_UNIT_RX = "|".join(f"(?P<{name}>{rx})" for name, rx in UNIT_WORDS.items())
_AMOUNT = r"(?P<amount>\d{1,4}(?:[.,]\d{1,2})?)"
# "£27.50 per hour", "£25/h", "£250 a day", "£ 220/day"
POUND_RX = re.compile(rf"£\s?{_AMOUNT}(?:\s*(?:-|to|–)\s*£?\s?(?P<amount2>\d{{1,4}}(?:[.,]\d{{1,2}})?))?\s*(?:{_UNIT_RX})?(?!\w)", re.I)
# "27.50 per hour", "250 per day" (no £ sign): only explicit units, so "10 hour days" is not pay
_PLAIN_UNITS = {
    "hour": r"(?:per\s*hour|p/h|/\s*hr?|an\s*hour|ph)",
    "day": r"(?:per\s*day|p/d|/\s*day|a\s*day|pd)",
    "week": r"(?:per\s*week|p/w|/\s*week|pw)",
    "m2": UNIT_WORDS["m2"],
}
PLAIN_RX = re.compile(
    rf"(?<![\d£.,]){_AMOUNT}\s*(?:{'|'.join(f'(?P<{n}>{rx})' for n, rx in _PLAIN_UNITS.items())})(?!\w)",
    re.I,
)
# "9hrs paid", "8 hours", "10hr days"
HOURS_RX = re.compile(r"(?<!\d)(\d{1,2})\s*(?:hrs?|hours?)\b(?!\s*(?:notice|drive|away))", re.I)


@dataclass(frozen=True)
class Pay:
    amount: float
    amount_to: float | None  # "£25-£28 per hour"
    unit: str | None  # "hour" | "day" | "week" | "m2" | None (not stated)

    def label(self) -> str:
        amount = _money(self.amount) + (f"–{_money(self.amount_to)}" if self.amount_to else "")
        return f"{amount}/{UNIT_LABELS[self.unit]}" if self.unit else amount


def _money(value: float) -> str:
    return f"£{value:.2f}" if value != int(value) else f"£{int(value)}"


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def _unit(match: re.Match[str]) -> str | None:
    return next((name for name in UNIT_WORDS if match.group(name)), None)


def extract_pay(text: str) -> list[Pay]:
    """All pay amounts found in the text, in order, without duplicates."""
    found: list[Pay] = []
    taken: list[range] = []
    for rx in (POUND_RX, PLAIN_RX):
        for m in rx.finditer(text):
            if any(m.start() in span for span in taken):
                continue
            amount = _to_float(m.group("amount"))
            unit = _unit(m)
            if amount <= 0 or (unit is None and rx is PLAIN_RX):
                continue
            amount_to = _to_float(m.group("amount2")) if "amount2" in m.groupdict() and m.group("amount2") else None
            pay = Pay(amount, amount_to, unit)
            taken.append(range(m.start(), m.end()))
            if pay not in found:
                found.append(pay)
    return found


def shift_hours(text: str) -> int | None:
    """Working hours per day if the post says so ("9hrs paid", "10 hour days")."""
    for m in HOURS_RX.finditer(text):
        hours = int(m.group(1))
        if 6 <= hours <= 14:
            return hours
    return None


def describe_pay(text: str) -> str:
    """One line for the Telegram message: "£25/год (≈ £225 за 9-год день)" or "не вказана"."""
    pays = extract_pay(text)
    if not pays:
        return "Оплата не вказана"
    parts = [pay.label() for pay in pays[:3]]
    hourly = next((p for p in pays if p.unit == "hour"), None)
    if hourly and not any(p.unit == "day" for p in pays):
        hours = shift_hours(text) or DEFAULT_DAY_HOURS
        rate = hourly.amount_to or hourly.amount
        low = hourly.amount * hours
        day = _money(low) if not hourly.amount_to else f"{_money(low)}–{_money(rate * hours)}"
        parts[0] += f" (≈ {day} за {hours}-год день)"
    return ", ".join(parts)
