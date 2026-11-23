"""Runtime state shared by the extension server and the Telegram bot (in memory only)."""

import time
from dataclasses import dataclass, field


@dataclass
class MonitorState:
    paused: bool = False  # /pause in Telegram: the extension skips visits
    extension_running: bool = False  # the extension reported "started" and not "stopped"
    last_seen: float | None = None  # time.time() of the last request from the extension
    last_posts_at: float | None = None  # time.time() when posts were last received
    silence_reported: bool = False  # "extension is silent" alert already sent
    started_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Called on every authorized request from the extension."""
        self.last_seen = time.time()

    def seconds_since_seen(self) -> float | None:
        return None if self.last_seen is None else time.time() - self.last_seen
