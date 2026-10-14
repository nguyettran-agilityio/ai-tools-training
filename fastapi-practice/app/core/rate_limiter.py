"""In-memory rate limiter guarding auth endpoints against brute-force
login / spam-register attempts.

Same "process-wide singleton, in-memory only" pattern as
`token_denylist.py` — resets on restart and isn't shared across worker
processes, an accepted limitation at this project's scale.
"""

# Standard library
from collections import defaultdict
from datetime import UTC, datetime, timedelta

# Local application
# core
from app.core.config import get_settings


class InMemoryRateLimiter:
    """Fixed-window counter: at most `max_attempts` calls per `window_seconds`,
    per key (e.g. client IP)."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window = timedelta(seconds=window_seconds)
        self._attempts: dict[str, list[datetime]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Records this attempt and returns whether it's within the limit."""
        now = datetime.now(UTC)
        cutoff = now - self._window
        recent = [attempt for attempt in self._attempts[key] if attempt > cutoff]

        if len(recent) >= self._max_attempts:
            self._attempts[key] = recent
            return False

        recent.append(now)
        self._attempts[key] = recent
        return True

    def reset(self) -> None:
        """Test helper: forget every tracked key."""
        self._attempts.clear()


_settings = get_settings()
_rate_limiter = InMemoryRateLimiter(
    max_attempts=_settings.auth_rate_limit_max_attempts,
    window_seconds=_settings.auth_rate_limit_window_seconds,
)


def get_rate_limiter() -> InMemoryRateLimiter:
    return _rate_limiter
