"""SQLite database with posts. Synchronous API; call it via asyncio.to_thread from async code.

Duplicates:
  * the same post_url is stored only once (add_post returns None for it);
  * the same author + same text seen before (e.g. cross-posted to several groups)
    is stored with is_duplicate=1 and is never a lead.
"""

import hashlib
import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lead_monitor.core.models import FacebookPost
from lead_monitor.filters.keywords import KeywordMatch

# Each item upgrades the schema by one version (PRAGMA user_version). Append only — never edit.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE posts (
        id                 INTEGER PRIMARY KEY,
        post_url           TEXT NOT NULL UNIQUE,
        group_id           TEXT NOT NULL,
        group_name         TEXT,
        author_name        TEXT,
        author_profile_url TEXT,
        text               TEXT NOT NULL,
        content_hash       TEXT NOT NULL,
        posted_at          TEXT,
        collected_at       TEXT NOT NULL,
        saved_at           TEXT NOT NULL,
        is_duplicate       INTEGER NOT NULL DEFAULT 0,
        is_lead            INTEGER NOT NULL DEFAULT 0,
        matched_keywords   TEXT NOT NULL DEFAULT '[]'
    );
    CREATE INDEX idx_posts_content_hash ON posts(content_hash);
    CREATE INDEX idx_posts_saved_at ON posts(saved_at);
    """,
]


@dataclass(frozen=True)
class StoredPost:
    id: int
    post: FacebookPost
    is_duplicate: bool
    is_lead: bool
    matched_keywords: list[str]


def content_hash(post: FacebookPost) -> str:
    """Same author + same text (ignoring case and spacing) -> same hash."""
    author = post.author_profile_url or post.author_name or ""
    text = re.sub(r"\s+", " ", post.text).strip().lower()
    return hashlib.sha256(f"{author}\n{text}".encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")  # safe for a reader (dashboard) + writer
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def schema_version(self) -> int:
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self) -> None:
        with self._lock:
            version = self.schema_version
            for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                with self._conn:
                    self._conn.executescript(sql)
                    self._conn.execute(f"PRAGMA user_version = {number}")

    # --- writing ----------------------------------------------------------------------

    def add_post(self, post: FacebookPost, match: KeywordMatch) -> StoredPost | None:
        """Saves a new post. Returns None if this post_url was already saved."""
        digest = content_hash(post)
        with self._lock, self._conn:
            seen = self._conn.execute(
                "SELECT 1 FROM posts WHERE post_url = ?", (post.post_url,)
            ).fetchone()
            if seen:
                return None
            is_duplicate = (
                self._conn.execute(
                    "SELECT 1 FROM posts WHERE content_hash = ? LIMIT 1", (digest,)
                ).fetchone()
                is not None
            )
            is_lead = match.is_lead and not is_duplicate
            cursor = self._conn.execute(
                """
                INSERT INTO posts (post_url, group_id, group_name, author_name, author_profile_url,
                                   text, content_hash, posted_at, collected_at, saved_at,
                                   is_duplicate, is_lead, matched_keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post.post_url,
                    post.group_id,
                    post.group_name,
                    post.author_name,
                    post.author_profile_url,
                    post.text,
                    digest,
                    post.posted_at.isoformat() if post.posted_at else None,
                    post.collected_at.isoformat(),
                    _now(),
                    int(is_duplicate),
                    int(is_lead),
                    json.dumps(match.matched, ensure_ascii=False),
                ),
            )
        return StoredPost(
            id=cursor.lastrowid,
            post=post,
            is_duplicate=is_duplicate,
            is_lead=is_lead,
            matched_keywords=list(match.matched),
        )

    # --- reading ----------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*)                         AS total,
                       COALESCE(SUM(is_lead), 0)        AS leads,
                       COALESCE(SUM(is_duplicate), 0)   AS duplicates,
                       COUNT(DISTINCT group_id)         AS groups
                FROM posts
                """
            ).fetchone()
        return dict(row)

    def recent_leads(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, saved_at, group_id, group_name, author_name, post_url, text,
                       matched_keywords
                FROM posts WHERE is_lead = 1 ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{**dict(r), "matched_keywords": json.loads(r["matched_keywords"])} for r in rows]
