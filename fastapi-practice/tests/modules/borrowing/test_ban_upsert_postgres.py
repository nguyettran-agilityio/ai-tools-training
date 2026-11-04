"""Concurrency test for `BorrowingBanRepository.extend` on Postgres. Skipped
unless `TEST_DATABASE_URL` is set (CI's Postgres job): in-memory SQLite has a
single connection, so two sessions cannot race there.

The sequential rules (later date wins, no stacking, `created_at` kept) are
covered by `test_repositories.py`, which also runs on Postgres in CI."""

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.book.models import Book
from app.modules.borrowing.mappers import to_borrowing_ban_read
from app.modules.borrowing.models import Borrowing, BorrowingBan
from app.modules.borrowing.repositories_sqlmodel import BorrowingBanRepository
from app.modules.category.models import Category
from app.modules.user.models import User
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="needs Postgres (set TEST_DATABASE_URL)"
)

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


def make_repo(session: Session) -> BorrowingBanRepository:
    return BorrowingBanRepository(SQLModelBackend(session, BorrowingBan, to_borrowing_ban_read))


def make_user_and_loans(db_engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    with Session(db_engine) as session:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="hashed", full_name="Jane")
        category = Category(name=f"Category {uuid.uuid4()}")
        session.add_all([user, category])
        session.flush()
        book = Book(
            title="Deep Work",
            author="Cal Newport",
            isbn=f"isbn-{uuid.uuid4()}",
            category_id=category.id,
            total_copies=2,
            available_copies=2,
        )
        session.add(book)
        session.flush()
        loans = [
            Borrowing(user_id=user.id, book_id=book.id, borrowed_at=NOW, due_date=NOW)
            for _ in range(2)
        ]
        session.add_all(loans)
        session.commit()
        return user.id, loans[0].id, loans[1].id


@pytest.mark.parametrize("later_goes_first", [True, False])
def test_concurrent_extends_keep_the_later_date(db_engine, later_goes_first):
    """Session A upserts and holds its transaction open; session B's upsert
    must wait on A's row lock, then see A's committed row. The later end
    date wins whichever transaction commits first."""
    user_id, loan_a, loan_b = make_user_and_loans(db_engine)
    early = NOW + timedelta(days=7)
    late = NOW + timedelta(days=9)
    until_a, until_b = (late, early) if later_goes_first else (early, late)
    errors: list[BaseException] = []

    def extend_in_b() -> None:
        try:
            with Session(db_engine) as session_b:
                make_repo(session_b).extend(user_id, until_b, loan_b, NOW + timedelta(hours=1))
                session_b.commit()
        except BaseException as exc:  # surfaced in the main thread below
            errors.append(exc)

    with Session(db_engine) as session_a:
        make_repo(session_a).extend(user_id, until_a, loan_a, NOW)

        thread_b = threading.Thread(target=extend_in_b)
        thread_b.start()
        thread_b.join(timeout=1)
        assert thread_b.is_alive(), "B's upsert should wait for A's uncommitted row"

        session_a.commit()

    thread_b.join(timeout=10)
    assert not thread_b.is_alive()
    assert errors == []

    with Session(db_engine) as session:
        ban = session.get(BorrowingBan, user_id)

    assert ban is not None
    assert ban.banned_until == late
    assert ban.source_borrowing_id == (loan_a if later_goes_first else loan_b)
    assert ban.created_at == NOW
