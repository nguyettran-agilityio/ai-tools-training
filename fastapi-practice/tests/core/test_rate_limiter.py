"""Unit tests for `InMemoryRateLimiter` — no DB, no TestClient. Compare with
`tests/test_auth_rate_limit.py` (same behavior, through the real HTTP API).
"""

from datetime import UTC, datetime
from unittest.mock import patch

from app.core.rate_limiter import InMemoryRateLimiter


class TestIsAllowed:
    def test_allows_up_to_max_attempts_then_blocks(self):
        limiter = InMemoryRateLimiter(max_attempts=3, window_seconds=60)

        assert limiter.is_allowed("1.2.3.4") is True
        assert limiter.is_allowed("1.2.3.4") is True
        assert limiter.is_allowed("1.2.3.4") is True
        assert limiter.is_allowed("1.2.3.4") is False

    def test_different_keys_are_tracked_independently(self):
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60)

        assert limiter.is_allowed("1.2.3.4") is True
        assert limiter.is_allowed("5.6.7.8") is True
        assert limiter.is_allowed("1.2.3.4") is False

    def test_attempts_outside_the_window_are_forgotten(self):
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60)

        with patch("app.core.rate_limiter.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 1, 1, tzinfo=UTC)
            assert limiter.is_allowed("1.2.3.4") is True
            assert limiter.is_allowed("1.2.3.4") is False

            # 61 seconds later — outside the 60s window, so the earlier
            # attempt no longer counts against the limit.
            mock_datetime.now.return_value = datetime(2026, 1, 1, 0, 1, 1, tzinfo=UTC)
            assert limiter.is_allowed("1.2.3.4") is True


class TestReset:
    def test_reset_forgets_every_key(self):
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60)
        limiter.is_allowed("1.2.3.4")
        assert limiter.is_allowed("1.2.3.4") is False

        limiter.reset()

        assert limiter.is_allowed("1.2.3.4") is True
