"""Reservation notification pipeline: return -> BackgroundTasks ->
ReservationService.notify_book_available -> InMemoryNotifier.

Design A': notify *everyone* still pending for a book on return, don't hold
availability, and only close a reservation out ("fulfilled") when its owner
actually borrows. Through the real HTTP API — `TestClient` runs
`BackgroundTasks` synchronously on context exit (see `client` fixture in
`conftest.py`), so by the time a `/return` request has come back, any
scheduled notification has already run.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.core.notifications import InMemoryNotifier, get_notifier, set_notifier
from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.book.mappers import to_book_read
from app.modules.book.models import Book
from app.modules.book.repositories_sqlmodel import BookRepository
from app.modules.reservation.mappers import to_reservation_read
from app.modules.reservation.models import Reservation
from app.modules.reservation.repositories_sqlmodel import ReservationRepository
from app.modules.reservation.services import ReservationService
from app.modules.user.mappers import to_user_read
from app.modules.user.models import User
from app.modules.user.repositories_sqlmodel import UserRepository


@pytest.fixture(autouse=True)
def _reset_notifier(client):
    """Force a fresh `InMemoryNotifier`. `get_notifier()` returns a
    process-wide singleton (see `app/core/notifications.py`), and
    `client`'s lifespan startup rebinds it to a real `WebSocketNotifier` on
    every test (see `main.py`) — this file needs the plain in-memory sink,
    so it reinstalls one after `client` has been set up (hence depending on
    `client` here, not just requesting it in each test)."""
    set_notifier(InMemoryNotifier())
    yield
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


def me(client, token, auth_headers):
    return client.get("/auth/me", headers=auth_headers(token)).json()


def my_reservation_for_book(client, token, auth_headers, book_id):
    response = client.get("/reservations/my", headers=auth_headers(token))
    items = response.json()["items"]
    return next(r for r in items if r["bookId"] == book_id)


def register_member(client, email, full_name) -> str:
    password = "supersecret"
    payload = {"email": email, "password": password, "fullName": full_name}
    client.post("/auth/register", json=payload)
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


@pytest.fixture
def member_b_token(client) -> str:
    return register_member(client, "member-b@example.com", "Member B")


@pytest.fixture
def member_c_token(client) -> str:
    return register_member(client, "member-c@example.com", "Member C")


class TestNotifyOnReturn:
    def test_return_notifies_all_pending_reservers_and_marks_them_notified(
        self, client, admin_token, member_token, member_b_token, member_c_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrowing = borrow(client, member_token, auth_headers, book["id"]).json()
        assert reserve(client, member_b_token, auth_headers, book["id"]).status_code == 201
        assert reserve(client, member_c_token, auth_headers, book["id"]).status_code == 201

        user_b = me(client, member_b_token, auth_headers)
        user_c = me(client, member_c_token, auth_headers)

        response = return_borrowing(client, member_token, auth_headers, borrowing["id"])
        assert response.status_code == 200

        notifier = get_notifier()
        sent_to_b = notifier.sent_to(uuid.UUID(user_b["id"]))
        sent_to_c = notifier.sent_to(uuid.UUID(user_c["id"]))
        assert len(sent_to_b) == 1
        assert len(sent_to_c) == 1
        assert sent_to_b[0].type == "BOOK_AVAILABLE"
        assert sent_to_b[0].book_id == uuid.UUID(book["id"])

        reservation_b = my_reservation_for_book(client, member_b_token, auth_headers, book["id"])
        reservation_c = my_reservation_for_book(client, member_c_token, auth_headers, book["id"])
        assert reservation_b["status"] == "notified"
        assert reservation_c["status"] == "notified"

    def test_first_reserver_to_borrow_is_fulfilled_second_stays_notified(
        self, client, admin_token, member_token, member_b_token, member_c_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrowing = borrow(client, member_token, auth_headers, book["id"]).json()
        reserve(client, member_b_token, auth_headers, book["id"])
        reserve(client, member_c_token, auth_headers, book["id"])
        return_borrowing(client, member_token, auth_headers, borrowing["id"])

        borrowed_by_b = borrow(client, member_b_token, auth_headers, book["id"])
        assert borrowed_by_b.status_code == 201

        reservation_b = my_reservation_for_book(client, member_b_token, auth_headers, book["id"])
        reservation_c = my_reservation_for_book(client, member_c_token, auth_headers, book["id"])
        assert reservation_b["status"] == "fulfilled"
        assert reservation_c["status"] == "notified"

        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 0

    def test_late_reserver_gets_202_existing_reservation_and_is_notified_on_the_next_return(
        self, client, admin_token, member_token, member_b_token, member_c_token, auth_headers
    ):
        """C is already `notified` (still waiting) when they try to borrow
        the still-unavailable book again — the auto-reserve safety net
        (see `tests/test_borrow_auto_reserve.py`) hands back their existing
        open reservation with 202 rather than erroring, and does not create
        a second row for them."""
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrowing = borrow(client, member_token, auth_headers, book["id"]).json()
        reserve(client, member_b_token, auth_headers, book["id"])
        reserve(client, member_c_token, auth_headers, book["id"])
        return_borrowing(client, member_token, auth_headers, borrowing["id"])
        borrowed_by_b = borrow(client, member_b_token, auth_headers, book["id"]).json()

        reservation_c_before = my_reservation_for_book(
            client, member_c_token, auth_headers, book["id"]
        )

        queued = borrow(client, member_c_token, auth_headers, book["id"])
        assert queued.status_code == 202
        assert queued.json()["id"] == reservation_c_before["id"]

        reservation_c = my_reservation_for_book(client, member_c_token, auth_headers, book["id"])
        assert reservation_c["status"] == "notified"

        # A future return notifies C again — their reservation was left open,
        # not consumed by someone else's borrow.
        user_c = me(client, member_c_token, auth_headers)
        get_notifier().reset()

        return_borrowing(client, member_b_token, auth_headers, borrowed_by_b["id"])

        assert len(get_notifier().sent_to(uuid.UUID(user_c["id"]))) == 1

    def test_return_with_no_pending_reservers_notifies_nobody_and_succeeds(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrowing = borrow(client, member_token, auth_headers, book["id"]).json()

        response = return_borrowing(client, member_token, auth_headers, borrowing["id"])

        assert response.status_code == 200
        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 1


class TestNotifyBookAvailableService:
    """Direct, non-HTTP checks on `ReservationService.notify_book_available`
    itself — `notify_book_available` is `async`, and this project has no
    `pytest-asyncio`/`anyio` test plugin configured, so it's driven with
    `asyncio.run` rather than an `async def` test."""

    def test_no_pending_reservations_returns_zero(self, db_engine):
        with Session(db_engine) as session:
            service = ReservationService(
                ReservationRepository(SQLModelBackend(session, Reservation, to_reservation_read)),
                BookRepository(SQLModelBackend(session, Book, to_book_read)),
                UserRepository(SQLModelBackend(session, User, to_user_read)),
                get_notifier(),
            )
            count = asyncio.run(service.notify_book_available(uuid.uuid4()))

        assert count == 0


class TestListPendingForBookOrdering:
    def test_returns_oldest_pending_reservation_first(
        self, client, db_engine, admin_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        book_id = uuid.UUID(book["id"])
        token_b = register_member(client, "b2@example.com", "B2")
        token_c = register_member(client, "c2@example.com", "C2")
        user_b_id = uuid.UUID(me(client, token_b, auth_headers)["id"])
        user_c_id = uuid.UUID(me(client, token_c, auth_headers)["id"])

        base = datetime.now(UTC)
        with Session(db_engine) as session:
            later = base + timedelta(seconds=5)
            session.add(Reservation(user_id=user_c_id, book_id=book_id, created_at=later))
            session.add(Reservation(user_id=user_b_id, book_id=book_id, created_at=base))
            session.commit()

        with Session(db_engine) as session:
            repo = ReservationRepository(SQLModelBackend(session, Reservation, to_reservation_read))
            pending = repo.list_pending_for_book(book_id)

        assert [r.user_id for r in pending] == [user_b_id, user_c_id]
