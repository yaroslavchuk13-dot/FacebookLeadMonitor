"""Keyword filter: a post is a lead if EVERY keyword group matches and no [exclude] term does.

Keyword file format (UTF-8 text):
    # comment
    [trade]              <- any section name except [exclude] is a group
    fire stop*           <- word starting with "fire stop" (stopper, stopping)
    passive fire         <- phrase, whole words, any case
    [location]
    london
    re:\\bse\\d{1,2}\\b    <- "re:" = regular expression (e.g. postcodes)
    [exclude]
    looking for work

A post must contain at least one term from each group ([trade] AND [location]).
If there are no groups at all, every post passes (filter disabled) — handy for testing.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

EXCLUDE_SECTION = "exclude"
REGEX_PREFIX = "re:"


@dataclass(frozen=True)
class KeywordMatch:
    is_lead: bool
    matched: list[str] = field(default_factory=list)  # terms found (all groups)
    excluded_by: list[str] = field(default_factory=list)  # [exclude] terms found
    missing_groups: list[str] = field(default_factory=list)  # groups with no match


def _normalize(text: str) -> str:
    return text.replace("’", "'").replace("ʼ", "'").lower()


def _is_meaningful(term: str) -> bool:
    return bool(term.strip().removeprefix(REGEX_PREFIX).strip().rstrip("*").strip())


def _compile_term(term: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive pattern; spaces match any whitespace; trailing * = prefix."""
    term = term.strip()
    if term.lower().startswith(REGEX_PREFIX):
        return re.compile(term[len(REGEX_PREFIX):].strip(), re.IGNORECASE)
    term = _normalize(term)
    prefix = term.endswith("*")
    words = term.rstrip("*").split()
    body = r"\s+".join(re.escape(word) for word in words)
    tail = r"\w*" if prefix else r"(?!\w)"
    return re.compile(rf"(?<!\w){body}{tail}")


class KeywordFilter:
    def __init__(
        self,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        groups: dict[str, list[str]] | None = None,
    ) -> None:
        all_groups = dict(groups or {})
        if include:
            all_groups.setdefault("include", []).extend(include)
        self.groups = {
            name: [t.strip() for t in terms if _is_meaningful(t)] for name, terms in all_groups.items()
        }
        self.groups = {name: terms for name, terms in self.groups.items() if terms}
        self.exclude = [t.strip() for t in exclude or [] if _is_meaningful(t)]
        self._groups = {
            name: [(t, _compile_term(t)) for t in terms] for name, terms in self.groups.items()
        }
        self._exclude = [(t, _compile_term(t)) for t in self.exclude]

    @property
    def include(self) -> list[str]:
        """All search terms of all groups (for statistics)."""
        return [term for terms in self.groups.values() for term in terms]

    @property
    def enabled(self) -> bool:
        return bool(self.groups)

    def match(self, text: str) -> KeywordMatch:
        normalized = _normalize(text)
        excluded_by = [term for term, rx in self._exclude if rx.search(normalized)]
        matched: list[str] = []
        missing: list[str] = []
        for name, patterns in self._groups.items():
            found = [term for term, rx in patterns if rx.search(normalized)]
            matched += found
            if not found:
                missing.append(name)
        return KeywordMatch(
            is_lead=not missing and not excluded_by,
            matched=matched,
            excluded_by=excluded_by,
            missing_groups=missing,
        )


def parse_keyword_text(content: str) -> KeywordFilter:
    groups: dict[str, list[str]] = {}
    exclude: list[str] = []
    current: list[str] | None = None
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        heading = re.fullmatch(r"\[(\w+)\]", line)
        if heading:
            name = heading.group(1).lower()
            current = exclude if name == EXCLUDE_SECTION else groups.setdefault(name, [])
            continue
        if current is None:
            log.warning("Keyword %r is outside any [section] — ignored", line)
            continue
        if line.lower().startswith(REGEX_PREFIX):
            try:
                re.compile(line[len(REGEX_PREFIX):].strip())
            except re.error as err:
                log.error("Invalid pattern %r in keyword file: %s — ignored", line, err)
                continue
        current.append(line)
    return KeywordFilter(exclude=exclude, groups=groups)


class KeywordFile:
    """Loads the keyword file and reloads it automatically when it changes on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._mtime: float | None = None
        self._filter = KeywordFilter()
        self._missing_reported = False

    def get(self) -> KeywordFilter:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            if not self._missing_reported:  # warn once, not on every post
                log.warning("Keyword file %s not found — keyword filter disabled", self.path)
                self._missing_reported = True
            self._mtime, self._filter = None, KeywordFilter()
            return self._filter
        self._missing_reported = False
        if mtime != self._mtime:
            # utf-8-sig: Visual Studio / PowerShell often save UTF-8 with a BOM.
            self._filter = parse_keyword_text(self.path.read_text(encoding="utf-8-sig"))
            self._mtime = mtime
            groups = ", ".join(f"[{name}] {len(terms)}" for name, terms in self._filter.groups.items())
            log.info(
                "Keywords loaded: %s, [exclude] %d%s",
                groups or "no groups",
                len(self._filter.exclude),
                "" if self._filter.enabled else " — filter disabled, every post is a lead",
            )
        return self._filter
