"""Tests for app_logging: secret masking, file output, rotation."""

import logging
from pathlib import Path

import pytest

import app_logging
from config import Settings

FAKE_TG_TOKEN = "123456789:AAFakeTokenForMaskingTest_1234567890"
FAKE_EXT_TOKEN = "myCustomExtSecret42"


@pytest.fixture
def log_dir(tmp_path: Path):
    """Set up logging into a temp folder and restore the root logger afterwards."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    settings = Settings(
        _env_file=None, log_dir=tmp_path, log_level="DEBUG", extension_token=FAKE_EXT_TOKEN
    )
    app_logging.setup_logging(settings)
    yield tmp_path
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()  # Windows: release the file so tmp_path can be deleted
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def read_log(folder: Path) -> str:
    for handler in logging.getLogger().handlers:
        handler.flush()
    return (folder / app_logging.LOG_FILE_NAME).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        (f"ext token {FAKE_EXT_TOKEN}", FAKE_EXT_TOKEN),
        (f"https://api.telegram.org/bot{FAKE_TG_TOKEN}/getMe", "AAFakeToken"),
        ("key sk-proj-FAKEfakeFAKEfake1234", "FAKEfake"),
        ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop"),
        ("api_key=qwertyuiop123", "qwertyuiop123"),
    ],
)
def test_secrets_masked_in_file(log_dir: Path, message: str, secret: str) -> None:
    logging.getLogger("t").info(message)
    text = read_log(log_dir)
    assert secret not in text
    assert app_logging.MASK in text


def test_secret_in_args_masked(log_dir: Path) -> None:
    logging.getLogger("t").info("value=%s", FAKE_EXT_TOKEN)
    assert FAKE_EXT_TOKEN not in read_log(log_dir)


def test_secret_in_traceback_masked(log_dir: Path) -> None:
    try:
        raise RuntimeError(f"failed with {FAKE_EXT_TOKEN}")
    except RuntimeError:
        logging.getLogger("t").exception("boom")
    text = read_log(log_dir)
    assert FAKE_EXT_TOKEN not in text
    assert "Traceback" in text and "RuntimeError" in text


def test_normal_text_not_changed(log_dir: Path) -> None:
    logging.getLogger("t").info("Group 12345 checked, 7 new posts")
    assert "Group 12345 checked, 7 new posts" in read_log(log_dir)


def test_repeated_setup_does_not_duplicate(log_dir: Path) -> None:
    settings = Settings(_env_file=None, log_dir=log_dir)
    app_logging.setup_logging(settings)
    logging.getLogger("t").info("only once")
    assert read_log(log_dir).count("only once") == 1


def test_rotation(log_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_logging, "MAX_BYTES", 2000)
    app_logging.setup_logging(Settings(_env_file=None, log_dir=log_dir))
    for i in range(200):
        logging.getLogger("t").info("line %d %s", i, "x" * 50)
    files = sorted(p.name for p in log_dir.iterdir())
    assert "app.log.1" in files
    assert len(files) == app_logging.BACKUP_COUNT + 1
