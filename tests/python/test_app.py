"""Tests for the app supervisor (restart pauses)."""

from types import SimpleNamespace

from lead_monitor.app import MAX_RESTART_DELAY_SECONDS, RESTART_DELAY_SECONDS, restart_delay


def test_backoff_grows_and_is_capped() -> None:
    error = RuntimeError("boom")
    delays = [restart_delay(attempt, error) for attempt in range(1, 10)]
    assert delays[0] == RESTART_DELAY_SECONDS
    assert delays[1] == RESTART_DELAY_SECONDS * 2
    assert delays == sorted(delays)
    assert delays[-1] == MAX_RESTART_DELAY_SECONDS


def test_telegram_retry_after_is_respected() -> None:
    """Restarting sooner than Telegram asks only extends the flood ban."""
    flood = SimpleNamespace(retry_after=600)
    assert restart_delay(1, flood) >= 605
    small = SimpleNamespace(retry_after=10)
    assert restart_delay(1, small) == RESTART_DELAY_SECONDS
