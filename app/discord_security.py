from __future__ import annotations

import re
import time
from collections import defaultdict

_REPO_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


def validate_repo_name(name: str) -> bool:
    """Validate a GitHub repository name (owner/repo format)."""
    if not name or ".." in name:
        return False
    return bool(_REPO_NAME_PATTERN.match(name))


class CommandRateLimiter:
    """Simple per-user, per-command rate limiter using a sliding window."""

    def __init__(self, max_calls: int = 5, window_seconds: float = 300) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)

    def _key(self, user_id: str, command: str) -> str:
        return f"{user_id}:{command}"

    def _cleanup(self, key: str) -> None:
        now = time.monotonic()
        self._calls[key] = [t for t in self._calls[key] if now - t < self.window_seconds]

    def allow(self, user_id: str, command: str) -> bool:
        """Check if a command is allowed and record it if so."""
        key = self._key(user_id, command)
        self._cleanup(key)
        if len(self._calls[key]) >= self.max_calls:
            return False
        self._calls[key].append(time.monotonic())
        return True

    def remaining(self, user_id: str, command: str) -> int:
        """Return the number of remaining allowed calls in the current window."""
        key = self._key(user_id, command)
        self._cleanup(key)
        return max(0, self.max_calls - len(self._calls[key]))
