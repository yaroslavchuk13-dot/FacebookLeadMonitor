"""Splits a job post into requirements, extra info and contacts (rules, no AI).

    "Requirements - LVL2 Passive fire protection"   -> requirements
    "Start date - ASAP", "Hours - 8am-4pm"          -> info
    "call 01708 206540", "jobs@mka-ltd.com"         -> contacts
"""

import re
from dataclasses import dataclass, field

from lead_monitor.filters.pay import extract_pay

MAX_ITEMS = 5
MAX_ITEM_CHARS = 90

PHONE_RE = re.compile(r"(?<![\d£])(?:\+44\s?\(?0?\)?\s?\d{2,4}|\(?0\d{2,4}\)?)[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
WHATSAPP_ONLY_RE = re.compile(r"\b(?:whatsapp|inbox|dm|pm|message me|send (?:me )?a message)\b", re.I)

REQUIREMENT_RE = re.compile(
    r"\b(?:cscs|ecs|nvq|lvl\s?\d|level\s?\d|ipaf|pasma|sssts|smsts|dbs|asbestos|first aid|"
    r"own tools?|tools|ppe|card|ticket|qualif\w*|certif\w*|experience\w*|experienced|"
    r"must (?:have|be|own)|required:|essential|driving licen[cs]e|licen[cs]e|own (?:car|van|vehicle|transport)|"
    r"vehicle|van|right to work|utr|references?|cv)\b",
    re.I,
)
INFO_RE = re.compile(
    r"\b(?:start\w*|asap|immediate\w*|tomorrow|monday|duration|weeks?|months?|long[ -]term|"
    r"hours?|hrs|\d{1,2}\s?(?:hrs?|hours?)|\d{1,2}\s?(?:am|pm)|shifts?|days? a week|cis|paye|parking|accommodation|"
    r"travel|duties|project|site|weekend\w*|overtime)\b",
    re.I,
)
LABEL_RE = re.compile(r"^(?:requirements?|essential|duties|role|details?|info|note)\s*[-:–]\s*", re.I)
BULLET_RE = re.compile(r"^[\s•●▪▫◦✅✔☑✓\-*–—>]+")


@dataclass
class JobDetails:
    requirements: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    contacts: list[str] = field(default_factory=list)


def find_contacts(text: str) -> list[str]:
    contacts: list[str] = []
    for m in PHONE_RE.finditer(text):
        phone = re.sub(r"\s+", " ", m.group(0)).strip()
        if len(re.sub(r"\D", "", phone)) >= 10 and phone not in contacts:
            contacts.append(phone)
    for m in EMAIL_RE.finditer(text):
        if m.group(0) not in contacts:
            contacts.append(m.group(0))
    if not contacts and (m := WHATSAPP_ONLY_RE.search(text)):
        contacts.append(f"{m.group(0)} (у дописі)")
    return contacts


def _segments(text: str) -> list[str]:
    """Lines, and long lines split into sentences."""
    parts: list[str] = []
    for line in text.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-ZА-ЯІЇЄ])", line):
            cleaned = BULLET_RE.sub("", sentence).strip().rstrip(".").strip()
            if cleaned:
                parts.append(cleaned)
    return parts


def _short(item: str) -> str:
    return item if len(item) <= MAX_ITEM_CHARS else item[:MAX_ITEM_CHARS].rstrip() + "…"


def extract_details(text: str, title: str | None = None) -> JobDetails:
    details = JobDetails(contacts=find_contacts(text))
    for segment in _segments(text):
        if title and segment.rstrip(".") in title:
            continue  # already shown as the title
        if PHONE_RE.search(segment) or EMAIL_RE.search(segment):
            continue  # contact line: shown in the contact block
        if extract_pay(segment) and len(segment) < 45:
            continue  # pay line: shown in the pay block
        item = _short(LABEL_RE.sub("", segment))
        is_duties = segment.lower().startswith("duties")
        if REQUIREMENT_RE.search(segment) and not is_duties:
            target = details.requirements
        elif INFO_RE.search(segment) or is_duties:
            target = details.info
        else:
            continue
        if item and item not in target and len(target) < MAX_ITEMS:
            target.append(item)
    return details
