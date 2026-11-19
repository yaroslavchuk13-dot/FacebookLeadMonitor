"""Logging setup: console + rotating file, with secrets masked everywhere.

Usage (once, at program start):
    from lead_monitor.core.log_setup import setup_logging
    setup_logging()
    log = logging.getLogger(__name__)
"""

import logging
import re
from logging.handlers import RotatingFileHandler

from lead_monitor.core.config import Settings, get_settings

LOG_FILE_NAME = "app.log"
MAX_BYTES = 1_000_000  # 1 MB per file
BACKUP_COUNT = 5  # app.log + app.log.1 ... app.log.5
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
MASK = "***"

# Generic patterns, so secrets are hidden even if they are not in .env.
SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Telegram bot token: 123456789:AA... (also inside .../bot<token>/...)
    # (no \b: in "bot123:..." there is no word boundary before the digits)
    re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"),
    # OpenAI-style keys: sk-..., sk-proj-...
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    # "token=..." / "api_key: ..." / "Authorization: Bearer ..." style values
    re.compile(
        r"(?i)((?:token|api[_-]?key|secret|password|bearer)[\"']?\s*[:=\s]\s*[\"']?)"
        r"[A-Za-z0-9._\-]{8,}"
    ),
]


class SecretMaskingFilter(logging.Filter):
    """Replaces known secret values and secret-like patterns with ***."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        # Longest first, so a secret that contains another one is fully masked.
        self._secrets = sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True)

    def mask(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, MASK)
        for pattern in SECRET_PATTERNS:
            if pattern.groups:
                text = pattern.sub(lambda m: m.group(1) + MASK, text)
            else:
                text = pattern.sub(MASK, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        # Render the final message (with args) once, then mask it.
        record.msg = self.mask(record.getMessage())
        record.args = None
        if record.exc_info:
            # Pre-format the traceback so it can be masked too.
            record.exc_text = self.mask(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        if record.exc_text:
            record.exc_text = self.mask(record.exc_text)
        return True


def _collect_secrets(settings: Settings) -> list[str]:
    values = [settings.telegram_bot_token, settings.openai_api_key, settings.extension_token]
    return [v.get_secret_value() for v in values if v is not None]


def setup_logging(settings: Settings | None = None) -> None:
    """Configure the root logger. Safe to call more than once."""
    settings = settings or get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    masking = SecretMaskingFilter(_collect_secrets(settings))
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        settings.log_dir / LOG_FILE_NAME,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()

    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler.addFilter(masking)

    root = logging.getLogger()
    # Remove handlers from a previous call to avoid duplicated lines.
    for old in root.handlers[:]:
        root.removeHandler(old)
        old.close()
    root.setLevel(settings.log_level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


if __name__ == "__main__":
    setup_logging()
    log = logging.getLogger("lead_monitor.demo")
    log.info("Logging works. File: %s", get_settings().log_dir / LOG_FILE_NAME)
    log.info("Fake URL: https://api.telegram.org/bot123456789:AAFakeTokenForMaskingTest_1234567890/sendMessage")
    log.info("Fake key: %s", "sk-proj-FAKEfakeFAKEfake1234")
