"""Tests for config.Settings. They never read the real .env file."""

import pytest
from pydantic import ValidationError

from lead_monitor.core.config import BASE_DIR, Settings

ENV_NAMES = [
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "AI_PROVIDER", "OLLAMA_BASE_URL",
    "OLLAMA_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "DATABASE_PATH", "LOG_DIR",
    "LOG_LEVEL", "EXTENSION_PORT", "EXTENSION_TOKEN",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure variables from the user's shell do not affect the tests."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_defaults() -> None:
    s = make()
    assert s.ai_provider == "none"
    assert s.extension_port == 8765
    assert s.log_level == "INFO"
    assert s.telegram_bot_token is None


def test_relative_paths_resolved_from_project_folder() -> None:
    s = make()
    assert s.database_path == BASE_DIR / "data" / "monitor.db"
    assert s.log_dir == BASE_DIR / "logs"


def test_absolute_path_kept(tmp_path) -> None:
    assert make(log_dir=tmp_path).log_dir == tmp_path


def test_empty_secret_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "   ")
    monkeypatch.setenv("EXTENSION_TOKEN", "")
    s = make()
    assert s.telegram_bot_token is None
    assert s.extension_token is None


def test_case_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", " Ollama ")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    s = make()
    assert s.ai_provider == "ollama"
    assert s.log_level == "DEBUG"


@pytest.mark.parametrize(
    ("field", "value"),
    [("ai_provider", "gemini"), ("log_level", "verbose"), ("extension_port", 80),
     ("extension_port", 70000)],
)
def test_invalid_values_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})


def test_safe_summary_hides_secrets() -> None:
    s = make(telegram_bot_token="123:SUPER_SECRET", openai_api_key="sk-SECRET")
    summary = s.safe_summary()
    text = str(summary)
    assert "SUPER_SECRET" not in text
    assert "sk-SECRET" not in text
    assert summary["telegram_bot_token"] == "***set***"
    assert summary["extension_token"] == "(not set)"
