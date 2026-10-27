"""Auto-reserve safety net on POST /borrowings.

Design: this is a safety net for the race condition where a member's UI
still showed a book as available (another borrow won the race between page
load and this request) — not a replacement for the proactive
`POST /reservations` path, which is untested here and stays unchanged (see
`tests/test_reservation_notify.py` for that). When `BorrowingService.borrow`
finds `available_copies <= 0` *after* the borrow-limit and
already-borrowing checks have both passed, it queues the caller into the
reservation queue and the router answers 202 instead of 409.
"""

import uuid

import pytest

from app.core.notifications import InMemoryNotifier, get_notifier, set_notifier


@pytest.fixture(autouse=True)
def _reset_notifier(client):
    """See the identical fixture in `test_reservation_notify.py`: `client`'s
    lifespan startup rebinds the process-wide notifier to a real
    `WebSocketNotifier`, so this reinstalls a plain in-memory sink after
    that has happened."""
    set_notifier(InMemoryNotifier())
    yield
    set_notifier(InMemoryNotifier())


def _in_memory_notifier() -> InMemoryNotifier:
    """`get_notifier()` is typed as the `Notifier` base; only the
    `InMemoryNotifier` installed by `_reset_notifier` has `sent_to`/`reset`."""
    notifier = get_notifier()
    assert isinstance(notifier, InMemoryNotifier)
    return notifier


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


def me(client, token, auth_headers):
    return client.get("/auth/me", headers=auth_headers(token)).json()


def my_reservations(client, token, auth_headers):
    response = client.get("/reservations/my", headers=auth_headers(token))
    return response.json()["items"]


def register_member(client, email, full_name="Member") -> str:
    password = "supersecret"
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "fullName": full_name},
    )
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


@pytest.fixture
def member_b_token(client) -> str:
    return register_member(client, "auto-reserve-b@example.com", "Member B")


class TestAutoReserveOnBorrow:
    def test_borrowing_out_of_stock_book_returns_202_and_queues_a_pending_reservation(
        self, client, admin_token, member_token, member_b_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        first = borrow(client, member_token, auth_headers, book["id"])
        assert first.status_code == 201

        queued = borrow(client, member_b_token, auth_headers, book["id"])

        assert queued.status_code == 202
        data = queued.json()
        assert data["status"] == "pending"
        assert data["bookId"] == book["id"]
        assert data["userId"] == me(client, member_b_token, auth_headers)["id"]

        # No copy was actually handed out.
        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 0

    def test_borrowing_same_out_of_stock_book_again_reuses_the_same_reservation(
        self, client, admin_token, member_token, member_b_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrow(client, member_token, auth_headers, book["id"])

        first_queue = borrow(client, member_b_token, auth_headers, book["id"])
        second_queue = borrow(client, member_b_token, auth_headers, book["id"])

        assert first_queue.status_code == 202
        assert second_queue.status_code == 202
        assert first_queue.json()["id"] == second_queue.json()["id"]

        reservations = my_reservations(client, member_b_token, auth_headers)
        matching = [r for r in reservations if r["bookId"] == book["id"]]
        assert len(matching) == 1

    def test_borrow_limit_still_returns_409_even_when_book_is_unavailable(
        self, client, admin_token, member_token, member_b_token, auth_headers
    ):
        """The limit check runs before the availability check, so a member
        already at their limit must not be auto-reserved into a book they
        have no room to borrow anyway."""
        books = [create_book(client, admin_token, auth_headers, totalCopies=1) for _ in range(5)]
        for book in books:
            response = borrow(client, member_token, auth_headers, book["id"])
            assert response.status_code == 201

        sixth_book = create_book(client, admin_token, auth_headers, totalCopies=1)
        # Someone else holds the sixth book too, so it's genuinely unavailable.
        other = borrow(client, member_b_token, auth_headers, sixth_book["id"])
        assert other.status_code == 201

        blocked = borrow(client, member_token, auth_headers, sixth_book["id"])

        assert blocked.status_code == 409
        assert "borrow limit" in blocked.json()["message"].lower()

    def test_already_borrowing_the_book_still_returns_409_not_202(
        self, client, admin_token, member_token, auth_headers
    ):
        """Borrowing the one-and-only copy you already hold hits the
        already-borrowing check (c) before the availability check (d) —
        `available_copies` is 0 precisely because you hold it, but that must
        still 409, not queue a self-reservation."""
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        first = borrow(client, member_token, auth_headers, book["id"])
        assert first.status_code == 201

        response = borrow(client, member_token, auth_headers, book["id"])

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"
        assert "already have this book" in response.json()["message"].lower()

    def test_auto_reserved_member_is_notified_when_the_book_is_returned(
        self, client, admin_token, member_token, member_b_token, auth_headers
    ):
        """End-to-end: an auto-created reservation participates in the same
        FIFO/notify pipeline as a manually created one (see
        `tests/test_reservation_notify.py`)."""
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        first = borrow(client, member_token, auth_headers, book["id"])
        queued = borrow(client, member_b_token, auth_headers, book["id"])
        assert queued.status_code == 202

        user_b = me(client, member_b_token, auth_headers)

        response = return_borrowing(client, member_token, auth_headers, first.json()["id"])
        assert response.status_code == 200

        notifier = _in_memory_notifier()
        sent_to_b = notifier.sent_to(uuid.UUID(user_b["id"]))
        assert len(sent_to_b) == 1
        assert sent_to_b[0].type == "BOOK_AVAILABLE"
        assert sent_to_b[0].book_id == uuid.UUID(book["id"])

        reservations = my_reservations(client, member_b_token, auth_headers)
        reservation_b = next(r for r in reservations if r["bookId"] == book["id"])
        assert reservation_b["status"] == "notified"

        # And B can now actually borrow it.
        retried = borrow(client, member_b_token, auth_headers, book["id"])
        assert retried.status_code == 201
