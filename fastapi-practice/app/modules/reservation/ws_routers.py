# Standard library
import uuid

# Third-party
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

# Local application
# core
from app.core.deps import get_user_repository
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.core.token_denylist import InMemoryTokenDenylist, get_token_denylist
from app.core.ws_manager import get_connection_manager

# user
from app.modules.user.repositories import UserRepositoryInterface

router = APIRouter(tags=["websocket"])

# WebSocket close code for "policy violation" (RFC 6455) — used here for any
# authentication failure (missing/invalid/expired/revoked token, unknown or
# inactive user).
WS_POLICY_VIOLATION = 1008


def _authenticate(
    token: str | None, user_repository: UserRepositoryInterface, denylist: InMemoryTokenDenylist
) -> uuid.UUID | None:
    """Decode + validate the JWT from a `?token=` query param (a `WebSocket`
    can't send an `Authorization` header). Returns `None` on any failure
    instead of raising, so the caller can close the socket uniformly."""
    if not token:
        return None

    try:
        payload = decode_access_token(token)
    except UnauthorizedError:
        return None

    if denylist.is_denied(payload.get("jti", "")):
        return None

    user = user_repository.get_by_id(uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        return None

    return user.id


@router.websocket("/ws/notifications")
async def notifications_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    user_repository: UserRepositoryInterface = Depends(get_user_repository),
    denylist: InMemoryTokenDenylist = Depends(get_token_denylist),
) -> None:
    user_id = _authenticate(token, user_repository, denylist)
    if user_id is None:
        # Reject before accepting, so the client sees the handshake fail
        # outright rather than a connection that opens and immediately
        # drops.
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    manager = get_connection_manager()
    await websocket.accept()
    manager.connect(user_id, websocket)
    try:
        while True:
            # This channel is push-only (server -> client); we don't expect
            # the client to send anything. `receive_text()` just blocks
            # until either a message arrives (ignored) or the client
            # disconnects, which is exactly what keeps the socket open.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, websocket)
