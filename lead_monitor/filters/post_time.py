"""Turns a Facebook timestamp text ("4h", "5 days ago", "Yesterday at 10:15") into a datetime."""

import re
from datetime import datetime, timedelta

# --- relative: "4h", "5 mins", "2 days ago", "4 год", "5 дн. назад" ---------------------------

UNIT_SECONDS = [
    (r"s|secs?|seconds?|сек\w*", 1),
    (r"m|mins?|minutes?|хв\w*|мин\w*", 60),
    (r"h|hrs?|hours?|год\w*|ч|час\w*", 3600),
    (r"d|days?|дн\w*|день|д", 86400),
    (r"w|wks?|weeks?|тиж\w*|нед\w*", 7 * 86400),
    (r"mo|months?|міс\w*|мес\w*", 30 * 86400),
    (r"y|yrs?|years?|р|рік|роки|років|г|год|года|лет", 365 * 86400),
]
_UNITS = "|".join(f"(?P<u{i}>{rx})" for i, (rx, _) in enumerate(UNIT_SECONDS))
RELATIVE_RE = re.compile(rf"^(?P<n>\d+|an?)\s*(?:{_UNITS})\.?(?:\s*(?:ago|тому|назад))?$", re.I)
NOW_RE = re.compile(r"^(?:just now|now|щойно|только что|зараз)$", re.I)

# --- day words + "at 10:15" -----------------------------------------------------------------------

TIME_PART = r"(?:\s*(?:at|о|об|в)\s*(?P<hour>\d{1,2})[:.](?P<minute>\d{2})\s*(?P<ampm>am|pm)?)?"
YESTERDAY_RE = re.compile(rf"^(?:yesterday|вчора|вчера){TIME_PART}$", re.I)
TODAY_RE = re.compile(rf"^(?:today|сьогодні|сегодня){TIME_PART}$", re.I)

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "понеділок": 0, "вівторок": 1, "середа": 2, "четвер": 3, "п'ятниця": 4, "субота": 5, "неділя": 6,
    "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3, "пятница": 4, "суббота": 5, "воскресенье": 6,
}
WEEKDAY_RE = re.compile(rf"^(?P<day>[^\W\d_']+(?:'[^\W\d_]+)?){TIME_PART}$", re.I)

# --- absolute: "21 November at 14:00", "November 21, 2024", "21 листопада о 14:00" ----------------

MONTHS = {
    1: ("jan", "січ", "янв"), 2: ("feb", "лют", "фев"), 3: ("mar", "бер", "мар"),
    4: ("apr", "квіт", "апр"), 5: ("may", "трав", "мая", "май"), 6: ("jun", "черв", "июн"),
    7: ("jul", "лип", "июл"), 8: ("aug", "серп", "авг"), 9: ("sep", "верес", "сен"),
    10: ("oct", "жовт", "окт"), 11: ("nov", "листоп", "ноя"), 12: ("dec", "груд", "дек"),
}
_YEAR = r"(?:,?\s*(?P<year>\d{4})(?:\s*(?:р|г)\.?)?)?"
# "Monday, 24 November 2026 at 13:40" (tooltip): the weekday in front of a full date is dropped
LEADING_WEEKDAY_RE = re.compile(rf"^(?:{'|'.join(WEEKDAYS)})\s*,?\s+(?=\d|[^\W\d_]+\s+\d)", re.I)
DAY_MONTH_RE = re.compile(rf"^(?P<d>\d{{1,2}})\s+(?P<month>[^\W\d_]+){_YEAR}{TIME_PART}$", re.I)
MONTH_DAY_RE = re.compile(rf"^(?P<month>[^\W\d_]+)\s+(?P<d>\d{{1,2}}){_YEAR}{TIME_PART}$", re.I)


def _month(name: str) -> int | None:
    lowered = name.lower()
    for number, prefixes in MONTHS.items():
        if any(lowered.startswith(p) for p in prefixes):
            return number
    return None


def _clock(match: re.Match[str], day: datetime) -> datetime:
    if match.group("hour") is None:
        return day.replace(hour=12, minute=0, second=0, microsecond=0)  # time unknown: midday
    hour, minute = int(match.group("hour")), int(match.group("minute"))
    ampm = (match.group("ampm") or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return day.replace(hour=12, minute=0, second=0, microsecond=0)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def parse_posted_text(text: str | None, now: datetime) -> datetime | None:
    """Best effort; None if the text is not understood. `now` should be timezone-aware."""
    if not text:
        return None
    value = re.sub(r"\s+", " ", text).strip().rstrip("·").strip()

    if NOW_RE.match(value):
        return now

    if m := RELATIVE_RE.match(value):
        count = 1 if m.group("n").lower() in ("a", "an") else int(m.group("n"))
        unit = next(i for i in range(len(UNIT_SECONDS)) if m.group(f"u{i}"))
        return now - timedelta(seconds=count * UNIT_SECONDS[unit][1])

    if m := YESTERDAY_RE.match(value):
        return _clock(m, now - timedelta(days=1))
    if m := TODAY_RE.match(value):
        return _clock(m, now)

    if (m := WEEKDAY_RE.match(value)) and m.group("day").lower() in WEEKDAYS:
        days_back = (now.weekday() - WEEKDAYS[m.group("day").lower()]) % 7 or 7
        return _clock(m, now - timedelta(days=days_back))

    value = LEADING_WEEKDAY_RE.sub("", value)
    for rx in (DAY_MONTH_RE, MONTH_DAY_RE):
        m = rx.match(value)
        month = _month(m.group("month")) if m else None
        if not m or month is None:
            continue
        year = int(m.group("year")) if m.group("year") else now.year
        try:
            result = _clock(m, now.replace(year=year, month=month, day=int(m.group("d"))))
        except ValueError:
            return None
        if not m.group("year") and result > now + timedelta(days=1):
            result = result.replace(year=year - 1)  # "21 December" seen in January
        return result
    return None


def describe_age(posted_at: datetime, now: datetime) -> str:
    """"5 хв тому", "4 год тому", "2 дн тому" + exact local date."""
    seconds = max(0, (now - posted_at).total_seconds())
    if seconds < 3600:
        ago = f"{max(1, int(seconds // 60))} хв тому"
    elif seconds < 86400:
        ago = f"{int(seconds // 3600)} год тому"
    else:
        ago = f"{int(seconds // 86400)} дн тому"
    return f"{ago} ({posted_at.astimezone(now.tzinfo).strftime('%d.%m %H:%M')})"
