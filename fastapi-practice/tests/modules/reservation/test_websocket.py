"""Realtime delivery: `ReservationService.notify_book_available` ->
`WebSocketNotifier` -> `/ws/notifications`.

`client`'s lifespan startup already wires the app's notifier to a
`WebSocketNotifier` bound to the process-wide `ConnectionManager` (see
`main.py`) — the `_wire_websocket_notifier` fixture below rebinds it
explicitly anyway, so this file stays correct even if that default wiring
ever changes.
"""

import uuid

import pytest
from fastapi import WebSocketDisconnect

from app.core.notifications import InMemoryNotifier, WebSocketNotifier, set_notifier
from app.core.ws_manager import get_connection_manager


@pytest.fixture(autouse=True)
def _wire_websocket_notifier(client):
    manager = get_connection_manager()
    manager.reset()
    set_notifier(WebSocketNotifier(manager))
    yield
    manager.reset()
    set_notifier(InMemoryNotifier())


def create_category(client, token, auth_headers, name=None):
    name = name or f"Cat {uuid.uuid4()}"
    response = client.post("/categories", json={"name": name}, headers=auth_headers(token))
    return response.json()["id"]


def create_book(client, admin_token, auth_headers, **overrides):
    category_id = overrides.pop("category_id", None) or create_category(
        client, admin_token, auth_headers
    )
    payload = {
        "title": "Clean Code",
        "author": "Robert C. Martin",
        "isbn": f"isbn-{uuid.uuid4()}",
        "categoryId": category_id,
        "totalCopies": 1,
    }
    payload.update(overrides)
    response = client.post("/books", json=payload, headers=auth_headers(admin_token))
    return response.json()


def borrow(client, token, auth_headers, book_id):
    return client.post("/borrowings", json={"bookId": book_id}, headers=auth_headers(token))


def return_borrowing(client, token, auth_headers, borrowing_id):
    return client.post(f"/borrowings/{borrowing_id}/return", headers=auth_headers(token))


def reserve(client, token, auth_headers, book_id):
    return client.post("/reservations", json={"bookId": book_id}, headers=auth_headers(token))


def register_member(client, email, full_name) -> str:
    password = "supersecret"
    payload = {"email": email, "password": password, "fullName": full_name}
    client.post("/auth/register", json=payload)
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


@pytest.fixture
def member_b_token(client) -> str:
    return register_member(client, "member-b@example.com", "Member B")


class TestConnectionAuth:
    def test_valid_token_is_accepted_and_stays_open(self, client, member_token):
        with client.websocket_connect(f"/ws/notifications?token={member_token}"):
            pass  # entering the context manager without raising = accepted

    def test_missing_token_is_rejected(self, client):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/notifications"):
                pass

    def test_garbage_token_is_rejected(self, client):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/notifications?token=not-a-real-jwt"):
                pass


class TestNotificationDelivery:
    def test_member_receives_book_available_notification_over_websocket(
        self, client, admin_token, member_token, member_b_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrowing = borrow(client, member_token, auth_headers, book["id"]).json()
        reserve(client, member_b_token, auth_headers, book["id"])

        with client.websocket_connect(f"/ws/notifications?token={member_b_token}") as ws:
            return_borrowing(client, member_token, auth_headers, borrowing["id"])
            message = ws.receive_json()

        assert message["type"] == "BOOK_AVAILABLE"
        assert message["bookId"] == book["id"]

    def test_two_connections_for_the_same_user_both_receive_the_message(
        self, client, admin_token, member_token, member_b_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrowing = borrow(client, member_token, auth_headers, book["id"]).json()
        reserve(client, member_b_token, auth_headers, book["id"])

        with (
            client.websocket_connect(f"/ws/notifications?token={member_b_token}") as ws1,
            client.websocket_connect(f"/ws/notifications?token={member_b_token}") as ws2,
        ):
            return_borrowing(client, member_token, auth_headers, borrowing["id"])
            message1 = ws1.receive_json()
            message2 = ws2.receive_json()

        assert message1["type"] == "BOOK_AVAILABLE"
        assert message2["type"] == "BOOK_AVAILABLE"
        assert message1["bookId"] == book["id"] == message2["bookId"]
