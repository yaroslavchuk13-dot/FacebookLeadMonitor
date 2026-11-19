"""Core data models shared by all parts of the app (data only, no business logic)."""

from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com"}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _check_facebook_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in FACEBOOK_HOSTS:
        raise ValueError("must be an https://facebook.com/... link")
    return value


class FacebookPost(BaseModel):
    """A post collected from a Facebook group by the Chrome extension."""

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True, extra="ignore")

    group_id: str = Field(min_length=1)
    group_name: str | None = None
    post_url: str
    author_name: str | None = None
    author_profile_url: str | None = None  # None for anonymous posts
    text: str = Field(min_length=1)
    posted_at: datetime | None = None  # if Facebook shows it
    collected_at: datetime = Field(default_factory=_utc_now)

    @field_validator("group_name", "author_name", "author_profile_url", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("post_url", "author_profile_url")
    @classmethod
    def _facebook_url(cls, value: str | None) -> str | None:
        return None if value is None else _check_facebook_url(value)

    @property
    def is_anonymous(self) -> bool:
        return self.author_profile_url is None


class ScamLevel(StrEnum):
    """Result of the author scam check (the last step of the pipeline)."""

    PENDING = "pending"  # check not finished yet
    GREEN = "green"  # no obvious scam signs found (not a 100% guarantee)
    YELLOW = "yellow"  # 1 red flag, mixed signals or too little data
    RED = "red"  # 2+ red flags

    @property
    def emoji(self) -> str:
        return {"pending": "👤", "green": "🟢", "yellow": "🟡", "red": "🔴"}[self.value]


class ScamCheckResult(BaseModel):
    """Only the verdict and human-readable signs are stored, no photos or personal data."""

    model_config = ConfigDict(frozen=True)

    level: ScamLevel = ScamLevel.PENDING
    red_flags: list[str] = Field(default_factory=list)
    green_flags: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=_utc_now)
