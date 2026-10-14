# Standard library
import logging
import uuid
from collections import defaultdict

# Third-party
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks live sockets per user — a `set[WebSocket]` since one user can
    have several open (e.g. two browser tabs)."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)

    def connect(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        self._connections[user_id].add(websocket)

    def disconnect(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id)

        if sockets is None:
            return
        sockets.discard(websocket)

        if not sockets:
            del self._connections[user_id]

    async def send_to_user(self, user_id: uuid.UUID, data: dict) -> None:
        """Push `data` to every socket the user has open; a no-op if none are
        open. A socket whose send fails is dropped, not raised."""
        for websocket in list(self._connections.get(user_id, ())):
            try:
                await websocket.send_json(data)
            except Exception:
                logger.warning("Dropping dead websocket for user %s", user_id)
                self.disconnect(user_id, websocket)

    def reset(self) -> None:
        """Test helper: forget every tracked connection without closing them."""
        self._connections.clear()


_manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Module-level singleton getter, same pattern as `notifications.get_notifier()`."""
    return _manager
