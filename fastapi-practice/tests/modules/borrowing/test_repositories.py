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
        reloaded = repo.get_by_id(borrowing.id)
        assert reloaded is not None
        assert reloaded.renewed_at == now


class TestListLateReturns:
    """`list_late_returns` against real SQLite: lateness filter, inclusive
    bounds, `returned_at` desc order (TC-42-03 / 04 / 06)."""

    def _make_repo(self, session: Session) -> BorrowingRepository:
        return BorrowingRepository(SQLModelBackend(session, Borrowing, to_borrowing_read))

    def _late_return(self, session: Session, returned_at: datetime) -> Borrowing:
        user = make_user(session)
        book = make_book(session, category_id=make_category(session).id)
        due_date = returned_at - timedelta(days=1)
        return make_borrowing(
            session,
            user.id,
            book.id,
            borrowed_at=due_date - timedelta(days=14),
            due_date=due_date,
            returned_at=returned_at,
        )

    def test_only_returns_after_due_date_newest_return_first(self, session):
        user = make_user(session)
        book = make_book(session, category_id=make_category(session).id)
        due_date = datetime(2026, 11, 1, 12, tzinfo=UTC)
        borrowed_at = due_date - timedelta(days=14)
        early = make_borrowing(
            session,
            user.id,
            book.id,
            borrowed_at=borrowed_at,
            due_date=due_date,
            returned_at=due_date - timedelta(hours=1),
        )
        exactly_at_due = make_borrowing(
            session,
            user.id,
            book.id,
            borrowed_at=borrowed_at,
            due_date=due_date,
            returned_at=due_date,
        )
        one_second_late = make_borrowing(
            session,
            user.id,
            book.id,
            borrowed_at=borrowed_at,
            due_date=due_date,
            returned_at=due_date + timedelta(seconds=1),
        )
        days_late = make_borrowing(
            session,
            user.id,
            book.id,
            borrowed_at=borrowed_at,
            due_date=due_date,
            returned_at=due_date + timedelta(days=3),
        )
        make_borrowing(session, user.id, book.id)  # unreturned

        items, total = self._make_repo(session).list_late_returns(0, 10)

        assert total == 2
        assert [item.id for item in items] == [days_late.id, one_second_late.id]
        assert early.id not in {item.id for item in items}
        assert exactly_at_due.id not in {item.id for item in items}

    def test_both_bounds_are_inclusive(self, session):
        t1 = datetime(2026, 11, 1, 8, tzinfo=UTC)
        t2 = datetime(2026, 11, 2, 8, tzinfo=UTC)
        t3 = datetime(2026, 11, 3, 8, tzinfo=UTC)
        first, second, third = (self._late_return(session, t) for t in (t1, t2, t3))
        repo = self._make_repo(session)

        items, total = repo.list_late_returns(0, 10, returned_from=t1, returned_to=t3)
        assert total == 3
        assert [item.id for item in items] == [third.id, second.id, first.id]

        items, total = repo.list_late_returns(0, 10, returned_from=t2, returned_to=t2)
        assert total == 1
        assert [item.id for item in items] == [second.id]

    def test_single_bound_applies_only_that_bound(self, session):
        before = self._late_return(session, datetime(2026, 11, 1, tzinfo=UTC))
        at = self._late_return(session, datetime(2026, 11, 2, tzinfo=UTC))
        after = self._late_return(session, datetime(2026, 11, 3, tzinfo=UTC))
        t = datetime(2026, 11, 2, tzinfo=UTC)
        repo = self._make_repo(session)

        items, _ = repo.list_late_returns(0, 10, returned_from=t)
        assert {item.id for item in items} == {at.id, after.id}

        items, _ = repo.list_late_returns(0, 10, returned_to=t)
        assert {item.id for item in items} == {before.id, at.id}

    def test_paginates_and_returns_utc_aware_datetimes(self, session):
        for day in (1, 2, 3):
            self._late_return(session, datetime(2026, 11, day, tzinfo=UTC))
        repo = self._make_repo(session)

        page1, total = repo.list_late_returns(0, 2)
        page2, _ = repo.list_late_returns(2, 2)

        assert total == 3
        assert len(page1) == 2
        assert len(page2) == 1
        assert {item.id for item in page1}.isdisjoint({item.id for item in page2})
        assert page1[0].returned_at is not None
        assert page1[0].returned_at.tzinfo is UTC
