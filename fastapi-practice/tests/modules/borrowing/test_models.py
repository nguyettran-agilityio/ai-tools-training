"""Borrowing model round-trip and constraint tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.modules.book.models import Book
from app.modules.borrowing.models import Borrowing
from app.modules.category.models import Category
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


class TestBorrowingModel:
    def test_insert_and_round_trip(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)

        borrowed_at = datetime.now(UTC)
        due_date = borrowed_at + timedelta(days=14)
        borrowing = Borrowing(
            user_id=user.id,
            book_id=book.id,
            borrowed_at=borrowed_at,
            due_date=due_date,
        )
        session.add(borrowing)
        session.commit()
        session.refresh(borrowing)

        fetched = session.get(Borrowing, borrowing.id)
        assert fetched is not None
        assert fetched.user_id == user.id
        assert fetched.book_id == book.id
        assert fetched.returned_at is None

    def test_has_no_status_column(self):
        assert "status" not in Borrowing.model_fields
        assert "is_overdue" not in Borrowing.model_fields
