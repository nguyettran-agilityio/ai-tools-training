"""BorrowingRepository tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.book.models import Book
from app.modules.borrowing.mappers import to_borrowing_ban_read, to_borrowing_read
from app.modules.borrowing.models import Borrowing, BorrowingBan
from app.modules.borrowing.repositories_sqlmodel import BorrowingBanRepository, BorrowingRepository
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


class TestBorrowingBanRepository:
    NOW = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)

    def _make_repo(self, session: Session) -> BorrowingBanRepository:
        return BorrowingBanRepository(SQLModelBackend(session, BorrowingBan, to_borrowing_ban_read))

    def _make_loans(self, session: Session, count: int = 2):
        user = make_user(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        loans = [make_borrowing(session, user.id, book.id) for _ in range(count)]
        return user, book, loans

    def test_extend_first_time_inserts_row(self, session):
        user, _, [loan, _] = self._make_loans(session)
        until = self.NOW + timedelta(days=7)

        ban = self._make_repo(session).extend(user.id, until, loan.id, self.NOW)

        assert ban.user_id == user.id
        assert ban.banned_until == until
        assert ban.source_borrowing_id == loan.id
        assert ban.created_at == self.NOW
        assert ban.updated_at == self.NOW

    @pytest.mark.parametrize("delta", [timedelta(days=-1), timedelta(0)])
    def test_extend_with_earlier_or_equal_date_leaves_row_unchanged(self, session, delta):
        user, _, [first, second] = self._make_loans(session)
        repo = self._make_repo(session)
        until = self.NOW + timedelta(days=7)
        repo.extend(user.id, until, first.id, self.NOW)

        later_now = self.NOW + timedelta(hours=1)
        ban = repo.extend(user.id, until + delta, second.id, later_now)

        assert ban.banned_until == until
        assert ban.source_borrowing_id == first.id
        assert ban.updated_at == self.NOW

    def test_extend_with_later_date_replaces_date_source_and_updated_at(self, session):
        user, _, [first, second] = self._make_loans(session)
        repo = self._make_repo(session)
        repo.extend(user.id, self.NOW + timedelta(days=7), first.id, self.NOW)

        later_now = self.NOW + timedelta(days=2)
        later_until = later_now + timedelta(days=7)
        ban = repo.extend(user.id, later_until, second.id, later_now)

        # Not stacked: the new end is `later_now + 7d`, not old end + 7d.
        assert ban.banned_until == later_until
        assert ban.source_borrowing_id == second.id
        assert ban.updated_at == later_now
        assert ban.created_at == self.NOW

    def test_extend_reuses_expired_row_and_keeps_created_at(self, session):
        user, _, [first, second] = self._make_loans(session)
        repo = self._make_repo(session)
        repo.extend(user.id, self.NOW + timedelta(days=7), first.id, self.NOW)

        much_later = self.NOW + timedelta(days=30)
        ban = repo.extend(user.id, much_later + timedelta(days=7), second.id, much_later)

        rows = session.exec(select(BorrowingBan).where(BorrowingBan.user_id == user.id)).all()
        assert len(rows) == 1
        assert ban.banned_until == much_later + timedelta(days=7)
        assert ban.created_at == self.NOW
        assert ban.updated_at == much_later

    def test_extend_out_of_order_calls_keep_the_latest_date(self, session):
        user, _, loans = self._make_loans(session, count=3)
        repo = self._make_repo(session)
        dates = [self.NOW + timedelta(days=d) for d in (5, 9, 7)]

        for loan, until in zip(loans, dates, strict=True):
            repo.extend(user.id, until, loan.id, self.NOW)

        ban = repo.get_by_id(user.id)
        assert ban is not None
        assert ban.banned_until == self.NOW + timedelta(days=9)
        assert ban.source_borrowing_id == loans[1].id

    def test_get_active_by_user_boundary(self, session):
        user, _, [loan, _] = self._make_loans(session)
        repo = self._make_repo(session)
        until = self.NOW + timedelta(days=7)
        repo.extend(user.id, until, loan.id, self.NOW)

        assert repo.get_active_by_user(user.id, until - timedelta(microseconds=1)) is not None
        # A ban ending exactly at `now` is over.
        assert repo.get_active_by_user(user.id, until) is None

    def test_list_active_excludes_expired_and_orders_soonest_first(self, session):
        repo = self._make_repo(session)
        category = make_category(session)
        book = make_book(session, category_id=category.id)
        ends = {}
        for days in (3, -1, 1):
            user = make_user(session)
            loan = make_borrowing(session, user.id, book.id)
            repo.extend(user.id, self.NOW + timedelta(days=days), loan.id, self.NOW)
            ends[days] = user.id

        items, total = repo.list_active(0, 10, self.NOW)

        assert total == 2
        assert [ban.user_id for ban in items] == [ends[1], ends[3]]

    def test_datetimes_read_back_as_utc_aware(self, session):
        user, _, [loan, _] = self._make_loans(session)
        repo = self._make_repo(session)
        repo.extend(user.id, self.NOW + timedelta(days=7), loan.id, self.NOW)
        session.commit()
        session.expire_all()

        ban = repo.get_by_id(user.id)

        assert ban is not None
        for value in (ban.banned_until, ban.created_at, ban.updated_at):
            assert value.tzinfo is UTC

    def test_deleting_user_deletes_ban(self, session):
        user, _, [loan, _] = self._make_loans(session)
        self._make_repo(session).extend(user.id, self.NOW + timedelta(days=7), loan.id, self.NOW)
        session.commit()

        session.delete(session.get(User, user.id))
        session.commit()
        session.expire_all()

        assert session.get(BorrowingBan, user.id) is None

    def test_deleting_source_borrowings_book_nulls_source(self, session):
        user, book, [loan, _] = self._make_loans(session)
        until = self.NOW + timedelta(days=7)
        self._make_repo(session).extend(user.id, until, loan.id, self.NOW)
        session.commit()

        # Book delete cascades to its borrowings; the ban must survive.
        session.delete(session.get(Book, book.id))
        session.commit()
        session.expire_all()

        ban = self._make_repo(session).get_by_id(user.id)
        assert ban is not None
        assert ban.source_borrowing_id is None
        assert ban.banned_until == until
