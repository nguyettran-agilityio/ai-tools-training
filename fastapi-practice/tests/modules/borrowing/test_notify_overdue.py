"""Admin-triggered overdue-reminder sweep: POST /borrowings/notify-overdue ->
BorrowingService.notify_overdue -> InMemoryNotifier.

Same shape as `tests/test_reservation_notify.py` (also driven through the
real HTTP API), except overdue borrowings can't be produced through the API
at all — they're seeded directly via `db_engine`, same as
`tests/test_borrowing_lists.py::test_returns_only_active_and_past_due_rows`.
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
from app.modules.borrowing.mappers import to_borrowing_ban_read, to_borrowing_read
from app.modules.borrowing.models import Borrowing, BorrowingBan
from app.modules.borrowing.repositories_sqlmodel import BorrowingBanRepository, BorrowingRepository
from app.modules.borrowing.services import BorrowingService
from app.modules.reservation.mappers import to_reservation_read
from app.modules.reservation.models import Reservation
from app.modules.reservation.repositories_sqlmodel import ReservationRepository
from app.modules.user.mappers import to_user_read
from app.modules.user.models import User
from app.modules.user.repositories_sqlmodel import UserRepository


@pytest.fixture(autouse=True)
def _reset_notifier(client):
    """Force a fresh `InMemoryNotifier` — see the identical fixture in
    `test_reservation_notify.py` for why this depends on `client`."""
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
        "totalCopies": 3,
    }
    payload.update(overrides)
    response = client.post("/books", json=payload, headers=auth_headers(admin_token))
    return response.json()


def get_my_id(client, token, auth_headers):
    return client.get("/auth/me", headers=auth_headers(token)).json()["id"]


def register_member(client, email, full_name) -> str:
    password = "supersecret"
    payload = {"email": email, "password": password, "fullName": full_name}
    client.post("/auth/register", json=payload)
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


@pytest.fixture
def member_b_token(client) -> str:
    return register_member(client, "member-b@example.com", "Member B")


def notify_overdue(client, token, auth_headers):
    return client.post("/borrowings/notify-overdue", headers=auth_headers(token))


class TestNotifyOverdueEndpoint:
    def test_notifies_only_truly_overdue_unreturned_holders(
        self, client, admin_token, member_token, member_b_token, auth_headers, db_engine
    ):
        book = create_book(client, admin_token, auth_headers)
        book_id = uuid.UUID(book["id"])
        member_id = uuid.UUID(get_my_id(client, member_token, auth_headers))
        member_b_id = uuid.UUID(get_my_id(client, member_b_token, auth_headers))
        past = datetime.now(UTC) - timedelta(days=20)
        future = datetime.now(UTC) + timedelta(days=5)

        with Session(db_engine) as session:
            # Member: overdue, still out — must be notified.
            session.add(
                Borrowing(
                    user_id=member_id,
                    book_id=book_id,
                    borrowed_at=past,
                    due_date=past + timedelta(days=14),
                    returned_at=None,
                )
            )
            # Member B: overdue, still out — must be notified.
            session.add(
                Borrowing(
                    user_id=member_b_id,
                    book_id=book_id,
                    borrowed_at=past,
                    due_date=past + timedelta(days=14),
                    returned_at=None,
                )
            )
            # Member: not yet due — must NOT be notified.
            session.add(
                Borrowing(
                    user_id=member_id,
                    book_id=book_id,
                    borrowed_at=datetime.now(UTC),
                    due_date=future,
                    returned_at=None,
                )
            )
            # Member B: overdue-looking due_date, but already returned — must
            # NOT be notified.
            session.add(
                Borrowing(
                    user_id=member_b_id,
                    book_id=book_id,
                    borrowed_at=past,
                    due_date=past + timedelta(days=14),
                    returned_at=datetime.now(UTC),
                )
            )
            session.commit()

        response = notify_overdue(client, admin_token, auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["remindersSent"] == 2

        notifier = _in_memory_notifier()
        sent_to_member = notifier.sent_to(member_id)
        sent_to_member_b = notifier.sent_to(member_b_id)
        assert len(sent_to_member) == 1
        assert len(sent_to_member_b) == 1
        assert sent_to_member[0].type == "OVERDUE_REMINDER"
        assert sent_to_member[0].book_id == book_id
        assert "overdue" in sent_to_member[0].message.lower()

    def test_no_overdue_borrowings_returns_zero_reminders_sent(
        self, client, admin_token, auth_headers
    ):
        response = notify_overdue(client, admin_token, auth_headers)

        assert response.status_code == 200
        assert response.json()["remindersSent"] == 0

    def test_member_returns_403(self, client, member_token, auth_headers):
        response = notify_overdue(client, member_token, auth_headers)

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_anonymous_returns_401(self, client):
        response = client.post("/borrowings/notify-overdue")

        assert response.status_code == 401


class TestNotifyOverdueService:
    """Direct, non-HTTP checks on `BorrowingService.notify_overdue` itself —
    same `asyncio.run` approach as
    `test_reservation_notify.py::TestNotifyBookAvailableService`, since this
    project has no `pytest-asyncio`/`anyio` plugin configured."""

    def test_no_overdue_borrowings_returns_zero(self, db_engine):
        with Session(db_engine) as session:
            service = BorrowingService(
                BorrowingRepository(SQLModelBackend(session, Borrowing, to_borrowing_read)),
                BookRepository(SQLModelBackend(session, Book, to_book_read)),
                ReservationRepository(SQLModelBackend(session, Reservation, to_reservation_read)),
                UserRepository(SQLModelBackend(session, User, to_user_read)),
                borrow_limit=5,
                loan_duration_days=14,
                renewal_days=14,
                notifier=get_notifier(),
                borrowing_ban_repository=BorrowingBanRepository(
                    SQLModelBackend(session, BorrowingBan, to_borrowing_ban_read)
                ),
                late_return_ban_days=7,
            )
            count = asyncio.run(service.notify_overdue())

        assert count == 0

    def test_does_not_mutate_borrowing_state(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """Read + notify only — the borrowing itself must come back
        untouched (still unreturned, same due_date) after the sweep."""
        book = create_book(client, admin_token, auth_headers)
        book_id = uuid.UUID(book["id"])
        member_id = uuid.UUID(get_my_id(client, member_token, auth_headers))
        past = datetime.now(UTC) - timedelta(days=20)
        due_date = past + timedelta(days=14)

        with Session(db_engine) as session:
            borrowing = Borrowing(
                user_id=member_id,
                book_id=book_id,
                borrowed_at=past,
                due_date=due_date,
                returned_at=None,
            )
            session.add(borrowing)
            session.commit()
            borrowing_id = borrowing.id

        with Session(db_engine) as session:
            service = BorrowingService(
                BorrowingRepository(SQLModelBackend(session, Borrowing, to_borrowing_read)),
                BookRepository(SQLModelBackend(session, Book, to_book_read)),
                ReservationRepository(SQLModelBackend(session, Reservation, to_reservation_read)),
                UserRepository(SQLModelBackend(session, User, to_user_read)),
                borrow_limit=5,
                loan_duration_days=14,
                renewal_days=14,
                notifier=get_notifier(),
                borrowing_ban_repository=BorrowingBanRepository(
                    SQLModelBackend(session, BorrowingBan, to_borrowing_ban_read)
                ),
                late_return_ban_days=7,
            )
            count = asyncio.run(service.notify_overdue())

        assert count == 1

        with Session(db_engine) as session:
            reloaded = session.get(Borrowing, borrowing_id)
            assert reloaded is not None
            assert reloaded.returned_at is None
