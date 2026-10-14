"""Reservation model round-trip and constraint tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator

import pytest
from sqlmodel import Session, text

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.modules.book.models import Book
from app.modules.category.models import Category
from app.modules.reservation.models import Reservation, ReservationStatus
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
    session.commit()
    session.refresh(user)
    return user


def make_category(session: Session, **overrides) -> Category:
    defaults = {"name": f"Category {uuid.uuid4()}"}
    defaults.update(overrides)
    category = Category(**defaults)
    session.add(category)
    session.commit()
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
    session.commit()
    session.refresh(book)
    return book


class TestReservationModel:
    def test_insert_and_round_trip(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)

        reservation = Reservation(user_id=user.id, book_id=book.id)
        session.add(reservation)
        session.commit()
        session.refresh(reservation)

        fetched = session.get(Reservation, reservation.id)
        assert fetched is not None
        assert fetched.status == ReservationStatus.PENDING
        assert fetched.status.value == "pending"
        assert fetched.notified_at is None

    def test_default_status_is_stored_as_lowercase_value(self, session):
        # Assert the RAW column value, not the ORM-decoded one — and that
        # the Python-side default ("pending") still reaches the DB despite
        # sa_column bypassing Field(default=...) at the schema level.
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        session.add(Reservation(user_id=user.id, book_id=book.id))
        session.commit()

        # Isolated per-test in-memory DB (see the `db_engine` fixture) — a
        # single reservation was just inserted, so no WHERE clause needed
        # (and none of the UUID-typed columns round-trip cleanly through a
        # plain-string bind param anyway — SQLite stores them as bare hex).
        raw_status = session.exec(text("SELECT status FROM reservation")).one()[0]
        assert raw_status == "pending"
