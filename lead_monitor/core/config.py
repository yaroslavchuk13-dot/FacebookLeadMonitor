"""Application settings loaded from environment variables and the .env file.

Run `python -m lead_monitor.core.config` to print the current settings (secrets are hidden).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: FacebookLeadMonitor/ (lead_monitor/core/config.py -> up 2 levels).
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All application settings in one typed object."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # AI
    ai_provider: Literal["none", "ollama", "openai"] = "none"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"

    # Storage and logs
    database_path: Path = Path("data/monitor.db")
    keywords_path: Path = Path("config/keywords.txt")
    log_dir: Path = Path("logs")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Chrome extension bridge
    extension_port: int = Field(default=8765, ge=1024, le=65535)
    extension_token: SecretStr | None = None

    @field_validator(
        "telegram_bot_token",
        "telegram_chat_id",
        "openai_api_key",
        "extension_token",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        """Treat empty values from .env (e.g. `TOKEN=`) as "not set"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ai_provider", mode="before")
    @classmethod
    def _lower_provider(cls, value: object) -> object:
        """Accept `Ollama`, ` OPENAI ` etc."""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        """Accept `info`, `Debug` etc."""
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("database_path", "keywords_path", "log_dir", mode="after")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        """Relative paths are resolved from the project folder, not the CWD."""
        return value if value.is_absolute() else (BASE_DIR / value).resolve()

    def safe_summary(self) -> dict[str, object]:
        """Settings as a dict that is safe to print or log (no secret values)."""
        summary: dict[str, object] = {}
        for name, value in self.model_dump().items():
            if isinstance(value, SecretStr):
                summary[name] = "***set***"
            elif value is None:
                summary[name] = "(not set)"
            else:
                summary[name] = str(value)
        return summary


@lru_cache
def get_settings() -> Settings:
    """Load settings once and reuse them across the app."""
    return Settings()


if __name__ == "__main__":
    for key, val in get_settings().safe_summary().items():
        print(f"{key:20} = {val}")
