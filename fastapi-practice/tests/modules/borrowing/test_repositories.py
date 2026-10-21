"""BorrowingRepository tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.book.models import Book
from app.modules.borrowing.mappers import to_borrowing_read
from app.modules.borrowing.models import Borrowing
from app.modules.borrowing.repositories_sqlmodel import BorrowingRepository
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


def make_borrowing(
    session: Session, user_id: uuid.UUID, book_id: uuid.UUID, **overrides
) -> Borrowing:
    borrowed_at = datetime.now(UTC) - timedelta(days=1)
    defaults = {
        "user_id": user_id,
        "book_id": book_id,
        "borrowed_at": borrowed_at,
        "due_date": borrowed_at + timedelta(days=14),
    }
    defaults.update(overrides)
    borrowing = Borrowing(**defaults)
    session.add(borrowing)
    session.flush()
    session.refresh(borrowing)
    return borrowing


class TestBorrowingRepository:
    def _make_repo(self, session: Session) -> BorrowingRepository:
        return BorrowingRepository(SQLModelBackend(session, Borrowing, to_borrowing_read))

    def test_count_active_by_user_ignores_returned_rows(self, session):
        user = make_user(session)
        category = make_category(session)
        book1 = make_book(session, category_id=category.id)
        book2 = make_book(session, category_id=category.id)
        make_borrowing(session, user.id, book1.id)  # active
        make_borrowing(session, user.id, book2.id, returned_at=datetime.now(UTC))  # returned

        repo = self._make_repo(session)
        assert repo.count_active_by_user(user.id) == 1
        assert len(repo.list_active_by_user(user.id)) == 1

    def test_list_all_overdue_only_returns_unreturned_past_due(self, session):
        user = make_user(session)
        category = make_category(session)
        book_overdue = make_book(session, category_id=category.id)
        book_active = make_book(session, category_id=category.id)
        book_returned_late = make_book(session, category_id=category.id)

        now = datetime.now(UTC)
        make_borrowing(
            session, user.id, book_overdue.id, due_date=now - timedelta(days=1), returned_at=None
        )
        make_borrowing(
            session, user.id, book_active.id, due_date=now + timedelta(days=5), returned_at=None
        )
        make_borrowing(
            session,
            user.id,
            book_returned_late.id,
            due_date=now - timedelta(days=1),
            returned_at=now,
        )

        repo = self._make_repo(session)
        items, total = repo.list_all(offset=0, limit=10, overdue_only=True, now=now)
        assert total == 1
        assert items[0].book_id == book_overdue.id

    def test_list_all_without_filter_returns_everything(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        make_borrowing(session, user.id, book.id)

        repo = self._make_repo(session)
        items, total = repo.list_all(offset=0, limit=10)
        assert total == 1
        assert len(items) == 1

    def test_get_active_by_user_and_book(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        borrowing = make_borrowing(session, user.id, book.id)

        repo = self._make_repo(session)
        found = repo.get_active_by_user_and_book(user.id, book.id)
        assert found is not None
        assert found.id == borrowing.id

    def test_count_active_by_book(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        make_borrowing(session, user.id, book.id)

        repo = self._make_repo(session)
        assert repo.count_active_by_book(book.id) == 1

    def test_mark_returned_sets_returned_at_and_returns_dto(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        borrowing = make_borrowing(session, user.id, book.id)

        repo = self._make_repo(session)
        returned_at = datetime.now(UTC)
        result = repo.mark_returned(borrowing.id, returned_at)

        assert result.returned_at == returned_at
        assert result.status == "returned"

    def test_mark_renewed_sets_due_date_and_renewed_at_as_utc(self, session):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        borrowing = make_borrowing(session, user.id, book.id)

        repo = self._make_repo(session)
        now = datetime.now(UTC)
        new_due = now + timedelta(days=20)
        result = repo.mark_renewed(borrowing.id, due_date=new_due, renewed_at=now)

        assert result.due_date == new_due
        assert result.renewed_at == now
        assert result.renewed_at.tzinfo is UTC
        assert repo.get_by_id(borrowing.id).renewed_at == now
