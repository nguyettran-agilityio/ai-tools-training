"""ReservationRepository tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.book.models import Book
from app.modules.category.models import Category
from app.modules.reservation.mappers import to_reservation_read
from app.modules.reservation.models import Reservation, ReservationStatus
from app.modules.reservation.repositories_sqlmodel import ReservationRepository
from app.modules.user.models import User


@pytest.fixture
def session(db_engine) -> Generator[Session, None, None]:
    with Session(db_engine) as session:
        yield session


def make_user(session: Session, **overrides) -> User:
    defaults = {
        "email": f"{uuid.uuid4()}@example.com",
        "hashed_password": "hashed",
        "full_name": "Jane Member",
    }
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    session.flush()
    session.refresh(user)
    return user


def make_category(session: Session, **overrides) -> Category:
    defaults = {"name": f"Category {uuid.uuid4()}"}
    defaults.update(overrides)
    category = Category(**defaults)
    session.add(category)
    session.flush()
    session.refresh(category)
    return category


def make_book(session: Session, category_id: uuid.UUID, **overrides) -> Book:
    defaults = {
        "title": "Deep Work",
        "author": "Cal Newport",
        "isbn": f"isbn-{uuid.uuid4()}",
        "category_id": category_id,
        "total_copies": 3,
        "available_copies": 3,
    }
    defaults.update(overrides)
    book = Book(**defaults)
    session.add(book)
    session.flush()
    session.refresh(book)
    return book


def make_reservation(
    session: Session, user_id: uuid.UUID, book_id: uuid.UUID, **overrides
) -> Reservation:
    defaults = {"user_id": user_id, "book_id": book_id}
    defaults.update(overrides)
    reservation = Reservation(**defaults)
    session.add(reservation)
    session.flush()
    session.refresh(reservation)
    return reservation


class TestReservationRepository:
    def _make_repo(self, session: Session) -> ReservationRepository:
        return ReservationRepository(SQLModelBackend(session, Reservation, to_reservation_read))

    def test_list_by_user(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        make_reservation(session, user.id, book.id)

        repo = self._make_repo(session)
        items, total = repo.list_by_user(user.id, offset=0, limit=10)
        assert total == 1
        assert len(items) == 1

    def test_mark_cancelled_sets_status(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        reservation = make_reservation(session, user.id, book.id)

        repo = self._make_repo(session)
        result = repo.mark_cancelled(reservation.id)

        assert result.status == ReservationStatus.CANCELLED

    def test_mark_notified_sets_status_and_notified_at(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        reservation = make_reservation(session, user.id, book.id)

        repo = self._make_repo(session)
        notified_at = datetime.now(UTC)
        result = repo.mark_notified(reservation.id, notified_at)

        assert result.status == ReservationStatus.NOTIFIED
        # SQLite round-trips naive (tzinfo dropped); unlike Borrowing's
        # mapper (`to_borrowing_read` / `_as_utc`), the reservation mapper
        # does no UTC normalization — compare the wall-clock value only.
        assert result.notified_at.replace(tzinfo=UTC) == notified_at

    def test_mark_fulfilled_sets_status(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        reservation = make_reservation(session, user.id, book.id)

        repo = self._make_repo(session)
        result = repo.mark_fulfilled(reservation.id)

        assert result.status == ReservationStatus.FULFILLED

    def test_count_open_by_book_ignores_fulfilled_and_cancelled(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        make_reservation(session, user.id, book.id, status=ReservationStatus.PENDING)
        make_reservation(
            session,
            make_user(session, email="b@x.com").id,
            book.id,
            status=ReservationStatus.NOTIFIED,
        )
        make_reservation(
            session,
            make_user(session, email="c@x.com").id,
            book.id,
            status=ReservationStatus.FULFILLED,
        )

        repo = self._make_repo(session)

        assert repo.count_open_by_book(book.id) == 2

    def test_count_open_by_user_ignores_fulfilled_and_cancelled(self, session):
        user = make_user(session)
        category = make_category(session)
        book_a = make_book(session, category_id=category.id, isbn="1111111111111")
        book_b = make_book(session, category_id=category.id, isbn="2222222222222")
        make_reservation(session, user.id, book_a.id, status=ReservationStatus.PENDING)
        make_reservation(session, user.id, book_b.id, status=ReservationStatus.CANCELLED)

        repo = self._make_repo(session)

        assert repo.count_open_by_user(user.id) == 1
