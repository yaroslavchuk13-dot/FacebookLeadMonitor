"""Keyword filter: a post is a lead if it contains an [include] term and no [exclude] term.

Keyword file format (UTF-8 text):
    # comment
    [include]
    fire stopping        <- phrase, whole words, any case
    plumb*               <- word starting with "plumb" (plumber, plumbing)
    [exclude]
    we are hiring

If [include] is empty, every post passes (filter disabled) — handy for testing.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

INCLUDE_SECTION = "include"
EXCLUDE_SECTION = "exclude"


@dataclass(frozen=True)
class KeywordMatch:
    is_lead: bool
    matched: list[str] = field(default_factory=list)  # [include] terms found
    excluded_by: list[str] = field(default_factory=list)  # [exclude] terms found


def _normalize(text: str) -> str:
    return text.replace("’", "'").replace("ʼ", "'").lower()


def _compile_term(term: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive pattern; spaces match any whitespace; trailing * = prefix."""
    term = _normalize(term.strip())
    prefix = term.endswith("*")
    words = term.rstrip("*").split()
    body = r"\s+".join(re.escape(word) for word in words)
    tail = r"\w*" if prefix else r"(?!\w)"
    return re.compile(rf"(?<!\w){body}{tail}")


class KeywordFilter:
    def __init__(self, include: list[str], exclude: list[str]) -> None:
        self.include = [t.strip() for t in include if t.strip().rstrip("*").strip()]
        self.exclude = [t.strip() for t in exclude if t.strip().rstrip("*").strip()]
        self._include = [(t, _compile_term(t)) for t in self.include]
        self._exclude = [(t, _compile_term(t)) for t in self.exclude]

    @property
    def enabled(self) -> bool:
        return bool(self.include)

    def match(self, text: str) -> KeywordMatch:
        normalized = _normalize(text)
        excluded_by = [term for term, rx in self._exclude if rx.search(normalized)]
        if not self.enabled:
            return KeywordMatch(is_lead=not excluded_by, excluded_by=excluded_by)
        matched = [term for term, rx in self._include if rx.search(normalized)]
        return KeywordMatch(
            is_lead=bool(matched) and not excluded_by, matched=matched, excluded_by=excluded_by
        )


def parse_keyword_text(content: str) -> KeywordFilter:
    sections: dict[str, list[str]] = {INCLUDE_SECTION: [], EXCLUDE_SECTION: []}
    current: str | None = None
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        heading = re.fullmatch(r"\[(\w+)\]", line)
        if heading:
            name = heading.group(1).lower()
            current = name if name in sections else None
            if current is None:
                log.warning("Unknown section [%s] in keyword file — ignored", name)
            continue
        if current is None:
            log.warning("Keyword %r is outside [include]/[exclude] — ignored", line)
            continue
        sections[current].append(line)
    return KeywordFilter(sections[INCLUDE_SECTION], sections[EXCLUDE_SECTION])


class KeywordFile:
    """Loads the keyword file and reloads it automatically when it changes on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._mtime: float | None = None
        self._filter = KeywordFilter([], [])
        self._missing_reported = False

    def get(self) -> KeywordFilter:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            if not self._missing_reported:  # warn once, not on every post
                log.warning("Keyword file %s not found — keyword filter disabled", self.path)
                self._missing_reported = True
            self._mtime, self._filter = None, KeywordFilter([], [])
            return self._filter
        self._missing_reported = False
        if mtime != self._mtime:
            # utf-8-sig: Visual Studio / PowerShell often save UTF-8 with a BOM.
            self._filter = parse_keyword_text(self.path.read_text(encoding="utf-8-sig"))
            self._mtime = mtime
            log.info(
                "Keywords loaded: %d include, %d exclude%s",
                len(self._filter.include),
                len(self._filter.exclude),
                "" if self._filter.enabled else " — [include] is empty, every post is a lead",
            )
        return self._filter
