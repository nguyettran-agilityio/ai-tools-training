# Standard library
from datetime import UTC, datetime


class InMemoryTokenDenylist:
    def __init__(self) -> None:
        self._denied: dict[str, datetime] = {}

    def add(self, jti: str, expires_at: datetime) -> None:
        self._purge_expired()
        self._denied[jti] = expires_at

    def is_denied(self, jti: str) -> bool:
        self._purge_expired()
        return jti in self._denied

    def _purge_expired(self) -> None:
        now = datetime.now(UTC)
        expired = [jti for jti, expires_at in self._denied.items() if expires_at <= now]
        for jti in expired:
            del self._denied[jti]


_denylist = InMemoryTokenDenylist()


def get_token_denylist() -> InMemoryTokenDenylist:
    return _denylist
