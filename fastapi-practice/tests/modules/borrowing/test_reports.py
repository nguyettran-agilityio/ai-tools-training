"""Unit tests for `BorrowingService.report_overdue` / `report_late_returns`
against fake repositories — no database, no `TestClient`.
"""

# Standard library
import uuid
from datetime import UTC, datetime, timedelta, timezone

# Third-party
import pytest

# Local application
from app.core.exceptions import BadRequestError
from app.core.notifications import InMemoryNotifier
from app.core.schemas import PaginationParams
from app.modules.book.schemas import BookRead
from app.modules.borrowing.services import BorrowingService
from app.modules.user.enums import UserRole
from app.modules.user.schemas import UserRead
from tests.fakes import (
    FakeBookRepository,
    FakeBorrowingRepository,
    FakeReservationRepository,
    FakeUserRepository,
)


class CountingUserRepository(FakeUserRepository):
    def __init__(self) -> None:
        super().__init__()
        self.lookups: list[uuid.UUID] = []

    def get_by_id(self, id: uuid.UUID) -> UserRead | None:
        self.lookups.append(id)
        return super().get_by_id(id)


class CountingBookRepository(FakeBookRepository):
    def __init__(self) -> None:
        super().__init__()
        self.lookups: list[uuid.UUID] = []

    def get_by_id(self, id: uuid.UUID) -> BookRead | None:
        self.lookups.append(id)
        return super().get_by_id(id)


@pytest.fixture
def user_repository():
    return CountingUserRepository()


@pytest.fixture
def book_repository():
    return CountingBookRepository()


@pytest.fixture
def borrowing_repository():
    return FakeBorrowingRepository()


@pytest.fixture
def service(book_repository, borrowing_repository, user_repository):
    return BorrowingService(
        borrowing_repository,
        book_repository,
        FakeReservationRepository(),
        user_repository,
        borrow_limit=5,
        loan_duration_days=14,
        renewal_days=14,
        notifier=InMemoryNotifier(),
    )


PAGE = PaginationParams(page=1, page_size=10)


def _make_user(user_repository: FakeUserRepository, email: str) -> UserRead:
    return user_repository.create(
        {
            "email": email,
            "full_name": "Report Member",
            "role": UserRole.MEMBER,
            "is_active": True,
            "hashed_password": "hashed",
        }
    )


def _make_book(book_repository: FakeBookRepository, title: str) -> BookRead:
    return book_repository.create(
        {
            "title": title,
            "author": "Someone",
            "isbn": f"isbn-{uuid.uuid4()}",
            "category_id": uuid.uuid4(),
            "total_copies": 1,
            "available_copies": 1,
        }
    )


def _make_borrowing(
    borrowing_repository,
    user_id: uuid.UUID,
    book_id: uuid.UUID,
    *,
    due_date: datetime,
    returned_at: datetime | None = None,
):
    return borrowing_repository.create(
        {
            "user_id": user_id,
            "book_id": book_id,
            "borrowed_at": due_date - timedelta(days=14),
            "due_date": due_date,
            "returned_at": returned_at,
        }
    )


def _late_return(borrowing_repository, user_id, book_id, returned_at: datetime):
    return _make_borrowing(
        borrowing_repository,
        user_id,
        book_id,
        due_date=returned_at - timedelta(days=1),
        returned_at=returned_at,
    )


class TestReportOverdue:
    def test_only_unreturned_past_due_rows_with_email_and_title(
        self, service, user_repository, book_repository, borrowing_repository
    ):
        """TC-42-01 (unit)."""
        user = _make_user(user_repository, "late@example.com")
        book = _make_book(book_repository, "Overdue Book")
        now = datetime.now(UTC)
        overdue = _make_borrowing(
            borrowing_repository, user.id, book.id, due_date=now - timedelta(days=2)
        )
        _make_borrowing(borrowing_repository, user.id, book.id, due_date=now + timedelta(days=2))
        _make_borrowing(
            borrowing_repository,
            user.id,
            book.id,
            due_date=now - timedelta(days=5),
            returned_at=now - timedelta(days=1),
        )

        page = service.report_overdue(PAGE)

        assert page.total == 1
        [row] = page.items
        assert row.id == overdue.id
        assert row.user_email == "late@example.com"
        assert row.book_title == "Overdue Book"
        assert row.status == "overdue"

    def test_orders_newest_borrow_first(
        self, service, user_repository, book_repository, borrowing_repository
    ):
        user = _make_user(user_repository, "late@example.com")
        book = _make_book(book_repository, "Overdue Book")
        now = datetime.now(UTC)
        older = _make_borrowing(
            borrowing_repository, user.id, book.id, due_date=now - timedelta(days=5)
        )
        newer = _make_borrowing(
            borrowing_repository, user.id, book.id, due_date=now - timedelta(days=1)
        )

        page = service.report_overdue(PAGE)

        assert [row.id for row in page.items] == [newer.id, older.id]


class TestReportLateReturns:
    def test_rows_carry_email_and_title(
        self, service, user_repository, book_repository, borrowing_repository
    ):
        user = _make_user(user_repository, "late@example.com")
        book = _make_book(book_repository, "Late Book")
        late = _late_return(
            borrowing_repository, user.id, book.id, datetime(2026, 11, 1, tzinfo=UTC)
        )

        page = service.report_late_returns(PAGE)

        [row] = page.items
        assert row.id == late.id
        assert row.user_email == "late@example.com"
        assert row.book_title == "Late Book"
        assert row.status == "returned"

    def test_naive_bound_is_treated_as_utc(
        self, service, user_repository, book_repository, borrowing_repository
    ):
        """TC-42-05."""
        user = _make_user(user_repository, "late@example.com")
        book = _make_book(book_repository, "Late Book")
        late = _late_return(
            borrowing_repository, user.id, book.id, datetime(2026, 11, 1, tzinfo=UTC)
        )

        page = service.report_late_returns(PAGE, returned_from=datetime(2026, 11, 1))

        assert [row.id for row in page.items] == [late.id]

    def test_offset_bound_is_converted_to_utc(
        self, service, user_repository, book_repository, borrowing_repository
    ):
        """Q-42-4: `07:00+07:00` is the same bound as `00:00Z`."""
        user = _make_user(user_repository, "late@example.com")
        book = _make_book(book_repository, "Late Book")
        at_midnight = _late_return(
            borrowing_repository, user.id, book.id, datetime(2026, 11, 1, tzinfo=UTC)
        )
        _late_return(
            borrowing_repository,
            user.id,
            book.id,
            datetime(2026, 11, 1, 0, 0, 1, tzinfo=UTC),
        )
        plus_seven = timezone(timedelta(hours=7))

        page = service.report_late_returns(
            PAGE, returned_to=datetime(2026, 11, 1, 7, tzinfo=plus_seven)
        )

        assert [row.id for row in page.items] == [at_midnight.id]

    def test_from_after_to_raises_bad_request(self, service):
        """TC-42-07."""
        with pytest.raises(BadRequestError, match="'from' must be before 'to'"):
            service.report_late_returns(
                PAGE,
                returned_from=datetime(2026, 11, 2, tzinfo=UTC),
                returned_to=datetime(2026, 11, 1, tzinfo=UTC),
            )

    def test_from_equal_to_is_allowed(
        self, service, user_repository, book_repository, borrowing_repository
    ):
        user = _make_user(user_repository, "late@example.com")
        book = _make_book(book_repository, "Late Book")
        t = datetime(2026, 11, 1, tzinfo=UTC)
        late = _late_return(borrowing_repository, user.id, book.id, t)

        page = service.report_late_returns(PAGE, returned_from=t, returned_to=t)

        assert [row.id for row in page.items] == [late.id]


class TestPerPageLookupCache:
    """TC-42-11: each distinct user and book is looked up once per page."""

    @pytest.fixture
    def two_users_two_books(self, user_repository, book_repository):
        users = [_make_user(user_repository, f"u{i}@example.com") for i in range(2)]
        books = [_make_book(book_repository, f"Book {i}") for i in range(2)]
        user_repository.lookups.clear()
        book_repository.lookups.clear()
        return users, books

    def test_overdue_report(
        self, service, user_repository, book_repository, borrowing_repository, two_users_two_books
    ):
        users, books = two_users_two_books
        now = datetime.now(UTC)
        for i in range(6):
            _make_borrowing(
                borrowing_repository,
                users[i % 2].id,
                books[i // 3].id,
                due_date=now - timedelta(days=i + 1),
            )

        page = service.report_overdue(PAGE)

        assert len(page.items) == 6
        assert sorted(user_repository.lookups) == sorted(user.id for user in users)
        assert sorted(book_repository.lookups) == sorted(book.id for book in books)

    def test_late_returns_report(
        self, service, user_repository, book_repository, borrowing_repository, two_users_two_books
    ):
        users, books = two_users_two_books
        for i in range(6):
            _late_return(
                borrowing_repository,
                users[i % 2].id,
                books[i // 3].id,
                datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=i),
            )

        page = service.report_late_returns(PAGE)

        assert len(page.items) == 6
        assert sorted(user_repository.lookups) == sorted(user.id for user in users)
        assert sorted(book_repository.lookups) == sorted(book.id for book in books)


class TestMissingReference:
    def test_missing_user_raises_lookup_error(self, service, book_repository, borrowing_repository):
        """Cannot happen with the real DB (borrowings cascade); fails loudly
        instead of building a row with a null email."""
        book = _make_book(book_repository, "Orphan")
        _late_return(borrowing_repository, uuid.uuid4(), book.id, datetime(2026, 11, 1, tzinfo=UTC))

        with pytest.raises(LookupError):
            service.report_late_returns(PAGE)
