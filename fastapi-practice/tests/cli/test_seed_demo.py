"""Tests for app/cli/seed_demo.py's core logic (seed_demo()), isolated from
argparse/CLI printing and from the real DB — same in-memory SQLite pattern
as tests/test_seed_admin.py.
"""

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.cli.seed_demo import ADMIN_EMAIL, CLEAN_BOOKS, MEMBERS, OVERDUE_BOOKS, seed_demo
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.security import verify_password
from app.modules.book.models import Book
from app.modules.borrowing.models import Borrowing
from app.modules.category.models import Category
from app.modules.reservation.models import Reservation
from app.modules.user.models import User, UserRole


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


class TestSeedDemoAccounts:
    def test_creates_admin_and_four_members(self, session):
        result = seed_demo(session, force=True)

        assert result.admin.email == ADMIN_EMAIL
        assert result.admin.role == UserRole.ADMIN

        # `UserRead` (what `seed_demo` returns) never carries the password
        # hash by design — verify it against the persisted rows instead.
        stored_admin = session.get(User, result.admin.id)
        assert verify_password("Admin@123", stored_admin.hashed_password)

        assert len(result.members) == 4
        assert [m.email for m in result.members] == [email for email, _ in MEMBERS]
        for member in result.members:
            assert member.role == UserRole.MEMBER
            stored_member = session.get(User, member.id)
            assert verify_password("Member@123", stored_member.hashed_password)


class TestSeedDemoCleanBooks:
    def test_six_clean_books_are_fully_available(self, session):
        result = seed_demo(session, force=True)

        assert len(result.clean_books) == 6
        assert [b.title for b in result.clean_books] == [title for title, *_ in CLEAN_BOOKS]
        for book in result.clean_books:
            assert book.available_copies == book.total_copies
            assert book.available_copies > 0

    def test_clean_books_have_no_borrowings_at_all(self, session):
        """No active borrowings — and no borrowings of any kind — on the
        clean books, so the demoer never hits stale state borrowing them
        live."""
        result = seed_demo(session, force=True)
        clean_book_ids = {b.id for b in result.clean_books}

        borrowings = session.exec(
            select(Borrowing).where(Borrowing.book_id.in_(clean_book_ids))
        ).all()
        assert borrowings == []


class TestSeedDemoOverdueBorrowings:
    def test_exactly_two_overdue_active_borrowings_for_first_member(self, session):
        result = seed_demo(session, force=True)
        now = datetime.now(UTC)

        assert len(result.overdue_borrowings) == 2
        for borrowing in result.overdue_borrowings:
            assert borrowing.user_id == result.members[0].id
            assert borrowing.returned_at is None
            due_date = borrowing.due_date.replace(tzinfo=UTC)
            assert due_date < now

    def test_overdue_books_are_dedicated_and_fully_checked_out(self, session):
        result = seed_demo(session, force=True)

        assert len(result.overdue_books) == 2
        overdue_book_ids = {b.id for b in result.overdue_books}
        clean_book_ids = {b.id for b in result.clean_books}
        assert overdue_book_ids.isdisjoint(clean_book_ids)

        assert [b.title for b in result.overdue_books] == [title for title, *_ in OVERDUE_BOOKS]
        for book in result.overdue_books:
            assert book.total_copies == 1
            assert book.available_copies == 0

    def test_no_other_borrowings_exist_beyond_the_two_overdue_ones(self, session):
        seed_demo(session, force=True)

        all_borrowings = session.exec(select(Borrowing)).all()
        assert len(all_borrowings) == 2
        assert all(b.returned_at is None for b in all_borrowings)


class TestSeedDemoNoReservations:
    def test_zero_reservations_created(self, session):
        seed_demo(session, force=True)

        assert session.exec(select(Reservation)).all() == []


class TestSeedDemoIdempotency:
    def test_without_force_second_call_is_a_no_op(self, session):
        seed_demo(session, force=True)

        result = seed_demo(session, force=False)

        assert result is None
        assert len(session.exec(select(User)).all()) == 5  # admin + 4 members, not duplicated
        assert len(session.exec(select(Category)).all()) == 3
        assert len(session.exec(select(Book)).all()) == 8  # 6 clean + 2 overdue

    def test_force_resets_members_but_keeps_the_same_admin_row(self, session):
        first = seed_demo(session, force=True)
        admin_id_before = first.admin.id
        first_member_id_before = first.members[0].id

        second = seed_demo(session, force=True)

        assert second.admin.id == admin_id_before  # admin is get-or-created, never deleted
        assert second.members[0].id != first_member_id_before  # members are wiped and recreated
        assert len(session.exec(select(User)).all()) == 5
        assert len(session.exec(select(Book)).all()) == 8
        assert len(session.exec(select(Borrowing)).all()) == 2
