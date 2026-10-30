"""Late-return ban: `BorrowingService.return_book` against fake repositories,
with the clock pinned by patching `services._now_utc`."""

# Standard library
import uuid
from datetime import UTC, datetime, timedelta

# Third-party
import pytest

# Local application
from app.core.exceptions import ConflictError, ForbiddenError
from app.core.notifications import InMemoryNotifier
from app.modules.borrowing import services
from app.modules.borrowing.services import BorrowingService
from tests.fakes import (
    FakeBookRepository,
    FakeBorrowingBanRepository,
    FakeBorrowingRepository,
    FakeReservationRepository,
    FakeUserRepository,
)

BAN_DAYS = 7
DUE = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
def book_repository():
    return FakeBookRepository()


@pytest.fixture
def borrowing_repository():
    return FakeBorrowingRepository()


@pytest.fixture
def ban_repository():
    return FakeBorrowingBanRepository()


@pytest.fixture
def notifier():
    return InMemoryNotifier()


def _make_service(book_repository, borrowing_repository, ban_repository, notifier, ban_days):
    return BorrowingService(
        borrowing_repository,
        book_repository,
        FakeReservationRepository(),
        FakeUserRepository(),
        borrow_limit=5,
        loan_duration_days=14,
        renewal_days=14,
        notifier=notifier,
        borrowing_ban_repository=ban_repository,
        late_return_ban_days=ban_days,
    )


@pytest.fixture
def service(book_repository, borrowing_repository, ban_repository, notifier):
    return _make_service(book_repository, borrowing_repository, ban_repository, notifier, BAN_DAYS)


@pytest.fixture
def clock(monkeypatch):
    """`clock.at(t)` pins `_now_utc()` to `t` for the next calls."""

    class _Clock:
        def at(self, value: datetime) -> None:
            monkeypatch.setattr(services, "_now_utc", lambda: value)

    return _Clock()


def _make_loan(book_repository, borrowing_repository, user_id, due_date=DUE):
    book = book_repository.create(
        {
            "title": "Deep Work",
            "author": "Cal Newport",
            "isbn": f"isbn-{uuid.uuid4()}",
            "category_id": uuid.uuid4(),
            "total_copies": 1,
            "available_copies": 0,
        }
    )
    return borrowing_repository.create(
        {
            "user_id": user_id,
            "book_id": book.id,
            "borrowed_at": due_date - timedelta(days=14),
            "due_date": due_date,
            "returned_at": None,
        }
    )


class TestBanOnReturn:
    def test_return_before_due_date_creates_no_ban(
        self, service, book_repository, borrowing_repository, ban_repository, clock
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(book_repository, borrowing_repository, user_id)
        clock.at(DUE - timedelta(days=1))

        service.return_book(user_id, loan.id)

        assert ban_repository.get_by_id(user_id) is None

    def test_return_exactly_at_due_date_is_on_time(
        self, service, book_repository, borrowing_repository, ban_repository, clock
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(book_repository, borrowing_repository, user_id)
        clock.at(DUE)

        service.return_book(user_id, loan.id)

        assert ban_repository.get_by_id(user_id) is None

    def test_return_one_second_late_bans_for_n_days(
        self, service, book_repository, borrowing_repository, ban_repository, clock
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(book_repository, borrowing_repository, user_id)
        returned_at = DUE + timedelta(seconds=1)
        clock.at(returned_at)

        returned = service.return_book(user_id, loan.id)

        # `due_date` read back from the repository is UTC-aware, like `now`.
        assert returned.due_date.tzinfo is not None
        ban = ban_repository.get_by_id(user_id)
        assert ban is not None
        assert ban.banned_until == returned_at + timedelta(days=BAN_DAYS)
        assert ban.source_borrowing_id == loan.id

    def test_later_late_return_moves_the_end_date_without_stacking(
        self, service, book_repository, borrowing_repository, ban_repository, clock
    ):
        user_id = uuid.uuid4()
        first = _make_loan(book_repository, borrowing_repository, user_id)
        second = _make_loan(book_repository, borrowing_repository, user_id)
        clock.at(DUE + timedelta(days=1))
        service.return_book(user_id, first.id)

        second_return = DUE + timedelta(days=3)
        clock.at(second_return)
        service.return_book(user_id, second.id)

        ban = ban_repository.get_by_id(user_id)
        assert ban is not None
        assert ban.banned_until == second_return + timedelta(days=BAN_DAYS)
        assert ban.source_borrowing_id == second.id

    def test_earlier_ending_late_return_leaves_the_ban_unchanged(
        self, book_repository, borrowing_repository, ban_repository, notifier, clock
    ):
        user_id = uuid.uuid4()
        first = _make_loan(book_repository, borrowing_repository, user_id)
        second = _make_loan(book_repository, borrowing_repository, user_id)
        long_ban = _make_service(
            book_repository, borrowing_repository, ban_repository, notifier, ban_days=30
        )
        short_ban = _make_service(
            book_repository, borrowing_repository, ban_repository, notifier, ban_days=BAN_DAYS
        )
        first_return = DUE + timedelta(days=1)
        clock.at(first_return)
        long_ban.return_book(user_id, first.id)

        clock.at(DUE + timedelta(days=2))
        short_ban.return_book(user_id, second.id)

        ban = ban_repository.get_by_id(user_id)
        assert ban is not None
        assert ban.banned_until == first_return + timedelta(days=30)
        assert ban.source_borrowing_id == first.id
        assert ban.updated_at == first_return

    def test_zero_ban_days_writes_a_row_that_is_never_active(
        self, book_repository, borrowing_repository, ban_repository, notifier, clock
    ):
        service = _make_service(
            book_repository, borrowing_repository, ban_repository, notifier, ban_days=0
        )
        user_id = uuid.uuid4()
        loan = _make_loan(book_repository, borrowing_repository, user_id)
        returned_at = DUE + timedelta(days=1)
        clock.at(returned_at)

        service.return_book(user_id, loan.id)

        ban = ban_repository.get_by_id(user_id)
        assert ban is not None
        assert ban.banned_until == returned_at
        assert ban_repository.get_active_by_user(user_id, returned_at) is None

    def test_late_return_sends_no_notification(
        self, service, book_repository, borrowing_repository, notifier, clock
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(book_repository, borrowing_repository, user_id)
        clock.at(DUE + timedelta(days=1))

        service.return_book(user_id, loan.id)

        assert notifier.sent_to(user_id) == []


class TestErrorPathsCreateNoBan:
    def test_returning_someone_elses_late_loan_raises_forbidden(
        self, service, book_repository, borrowing_repository, ban_repository, clock
    ):
        owner_id = uuid.uuid4()
        other_id = uuid.uuid4()
        loan = _make_loan(book_repository, borrowing_repository, owner_id)
        clock.at(DUE + timedelta(days=1))

        with pytest.raises(ForbiddenError):
            service.return_book(other_id, loan.id)

        assert ban_repository.get_by_id(owner_id) is None
        assert ban_repository.get_by_id(other_id) is None

    def test_returning_twice_raises_conflict_and_keeps_the_ban(
        self, service, book_repository, borrowing_repository, ban_repository, clock
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(book_repository, borrowing_repository, user_id)
        clock.at(DUE + timedelta(days=1))
        service.return_book(user_id, loan.id)
        before = ban_repository.get_by_id(user_id)

        clock.at(DUE + timedelta(days=5))
        with pytest.raises(ConflictError):
            service.return_book(user_id, loan.id)

        assert ban_repository.get_by_id(user_id) == before
