"""Unit tests for `BorrowingService` against fake repositories — no
database, no session, no `TestClient`. Compare with `tests/test_borrowings.py`
(same behavior, through the real HTTP API + DB).
"""

# Standard library
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

# Third-party
import pytest

# Local application
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.notifications import InMemoryNotifier
from app.modules.borrowing.schemas import BorrowOutcome, BorrowRequest
from app.modules.borrowing.services import BorrowingService
from tests.fakes import (
    FakeBookRepository,
    FakeBorrowingBanRepository,
    FakeBorrowingRepository,
    FakeReservationRepository,
    FakeUserRepository,
)


@pytest.fixture
def book_repository():
    return FakeBookRepository()


@pytest.fixture
def borrowing_repository():
    return FakeBorrowingRepository()


@pytest.fixture
def reservation_repository():
    return FakeReservationRepository()


@pytest.fixture
def user_repository():
    return FakeUserRepository()


@pytest.fixture
def notifier():
    return InMemoryNotifier()


@pytest.fixture
def service(
    book_repository, borrowing_repository, reservation_repository, user_repository, notifier
):
    return BorrowingService(
        borrowing_repository,
        book_repository,
        reservation_repository,
        user_repository,
        borrow_limit=2,
        loan_duration_days=14,
        # Deliberately != `loan_duration_days`, so `TestRenew` proves the
        # renewal extension comes from `renewal_days`, not the loan length.
        renewal_days=7,
        notifier=notifier,
        borrowing_ban_repository=FakeBorrowingBanRepository(),
        late_return_ban_days=7,
    )


def _make_book(book_repository, total_copies: int = 1, available_copies: int | None = None):
    return book_repository.create(
        {
            "title": "Deep Work",
            "author": "Cal Newport",
            "isbn": f"isbn-{uuid.uuid4()}",
            "category_id": uuid.uuid4(),
            "total_copies": total_copies,
            "available_copies": total_copies if available_copies is None else available_copies,
        }
    )


class TestBorrow:
    def test_unknown_book_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.borrow(uuid.uuid4(), BorrowRequest(book_id=uuid.uuid4()))

    def test_available_copy_is_borrowed_and_decrements_available_copies(
        self, service, book_repository
    ):
        book = _make_book(book_repository)
        user_id = uuid.uuid4()

        result = service.borrow(user_id, BorrowRequest(book_id=book.id))

        assert result.kind == BorrowOutcome.BORROWED
        assert result.borrowing.user_id == user_id
        assert book_repository.get_by_id(book.id).available_copies == 0

    def test_no_copies_left_queues_a_reservation_instead(self, service, book_repository):
        book = _make_book(book_repository, total_copies=1, available_copies=0)
        user_id = uuid.uuid4()

        result = service.borrow(user_id, BorrowRequest(book_id=book.id))

        assert result.kind == BorrowOutcome.RESERVED
        assert result.reservation.user_id == user_id

    def test_reusing_an_existing_open_reservation_does_not_duplicate_it(
        self, service, book_repository, reservation_repository
    ):
        book = _make_book(book_repository, total_copies=1, available_copies=0)
        user_id = uuid.uuid4()

        first = service.borrow(user_id, BorrowRequest(book_id=book.id))
        second = service.borrow(user_id, BorrowRequest(book_id=book.id))

        assert first.reservation.id == second.reservation.id
        _, total = reservation_repository.list_by_user(user_id, 0, 10)
        assert total == 1

    def test_borrowing_fulfills_the_callers_own_open_reservation(
        self, service, book_repository, reservation_repository
    ):
        book = _make_book(book_repository, total_copies=1, available_copies=0)
        user_id = uuid.uuid4()
        reservation = service.borrow(user_id, BorrowRequest(book_id=book.id)).reservation

        # A copy comes back, then the same user borrows it.
        book_repository.increment_available_copies(book.id)
        service.borrow(user_id, BorrowRequest(book_id=book.id))

        assert reservation_repository.get_by_id(reservation.id).status == "fulfilled"

    def test_borrow_limit_reached_raises_conflict(self, service, book_repository):
        book_a = _make_book(book_repository, total_copies=1)
        book_b = _make_book(book_repository, total_copies=1)
        book_c = _make_book(book_repository, total_copies=1)
        user_id = uuid.uuid4()

        service.borrow(user_id, BorrowRequest(book_id=book_a.id))
        service.borrow(user_id, BorrowRequest(book_id=book_b.id))  # hits borrow_limit=2

        with pytest.raises(ConflictError):
            service.borrow(user_id, BorrowRequest(book_id=book_c.id))

    def test_already_holding_the_same_book_raises_conflict(self, service, book_repository):
        book = _make_book(book_repository, total_copies=2)
        user_id = uuid.uuid4()
        service.borrow(user_id, BorrowRequest(book_id=book.id))

        with pytest.raises(ConflictError):
            service.borrow(user_id, BorrowRequest(book_id=book.id))


class TestReturnBook:
    def test_returning_gives_the_copy_back(self, service, book_repository):
        book = _make_book(book_repository, total_copies=1)
        user_id = uuid.uuid4()
        borrowing = service.borrow(user_id, BorrowRequest(book_id=book.id)).borrowing

        result = service.return_book(user_id, borrowing.id)

        assert result.status == "returned"
        assert book_repository.get_by_id(book.id).available_copies == 1

    def test_missing_borrowing_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.return_book(uuid.uuid4(), uuid.uuid4())

    def test_returning_someone_elses_borrowing_raises_forbidden(self, service, book_repository):
        book = _make_book(book_repository, total_copies=1)
        owner = uuid.uuid4()
        borrowing = service.borrow(owner, BorrowRequest(book_id=book.id)).borrowing

        with pytest.raises(ForbiddenError):
            service.return_book(uuid.uuid4(), borrowing.id)

    def test_returning_twice_raises_conflict(self, service, book_repository):
        book = _make_book(book_repository, total_copies=1)
        user_id = uuid.uuid4()
        borrowing = service.borrow(user_id, BorrowRequest(book_id=book.id)).borrowing
        service.return_book(user_id, borrowing.id)

        with pytest.raises(ConflictError):
            service.return_book(user_id, borrowing.id)


def _make_loan(borrowing_repository, user_id, due_in_days: int = 3, **overrides):
    now = datetime.now(UTC)
    data = {
        "user_id": user_id,
        "book_id": uuid.uuid4(),
        "borrowed_at": now - timedelta(days=14 - due_in_days),
        "due_date": now + timedelta(days=due_in_days),
        "returned_at": None,
    }
    data.update(overrides)
    return borrowing_repository.create(data)


class TestRenew:
    def test_extends_due_date_by_renewal_days_and_records_renewed_at(
        self, service, borrowing_repository
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(borrowing_repository, user_id)

        renewed = service.renew(user_id, loan.id)

        assert renewed.due_date == loan.due_date + timedelta(days=7)
        assert renewed.renewed_at is not None
        assert borrowing_repository.get_by_id(loan.id).due_date == renewed.due_date

    def test_second_renewal_raises_conflict(self, service, borrowing_repository):
        user_id = uuid.uuid4()
        loan = _make_loan(borrowing_repository, user_id)
        service.renew(user_id, loan.id)

        with pytest.raises(ConflictError, match="already been renewed"):
            service.renew(user_id, loan.id)

    def test_overdue_loan_raises_conflict(self, service, borrowing_repository):
        user_id = uuid.uuid4()
        loan = _make_loan(borrowing_repository, user_id, due_in_days=-1)

        with pytest.raises(ConflictError, match="Overdue"):
            service.renew(user_id, loan.id)

        assert borrowing_repository.get_by_id(loan.id).renewed_at is None

    @pytest.mark.parametrize("notified", [False, True])
    def test_another_members_open_reservation_raises_conflict(
        self, service, borrowing_repository, reservation_repository, notified
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(borrowing_repository, user_id)
        reservation = reservation_repository.create(
            {"user_id": uuid.uuid4(), "book_id": loan.book_id}
        )
        if notified:
            reservation_repository.mark_notified(reservation.id, datetime.now(UTC))

        with pytest.raises(ConflictError, match="open reservation"):
            service.renew(user_id, loan.id)

    def test_closed_reservation_by_another_member_does_not_block(
        self, service, borrowing_repository, reservation_repository
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(borrowing_repository, user_id)
        reservation = reservation_repository.create(
            {"user_id": uuid.uuid4(), "book_id": loan.book_id}
        )
        reservation_repository.mark_cancelled(reservation.id)

        assert service.renew(user_id, loan.id).renewed_at is not None

    def test_callers_own_open_reservation_does_not_block(
        self, service, borrowing_repository, reservation_repository
    ):
        user_id = uuid.uuid4()
        loan = _make_loan(borrowing_repository, user_id)
        reservation_repository.create({"user_id": user_id, "book_id": loan.book_id})

        assert service.renew(user_id, loan.id).renewed_at is not None

    def test_returned_loan_raises_conflict(self, service, borrowing_repository):
        user_id = uuid.uuid4()
        loan = _make_loan(borrowing_repository, user_id, returned_at=datetime.now(UTC))

        with pytest.raises(ConflictError, match="already returned"):
            service.renew(user_id, loan.id)

    def test_someone_elses_loan_raises_forbidden(self, service, borrowing_repository):
        loan = _make_loan(borrowing_repository, uuid.uuid4())

        with pytest.raises(ForbiddenError):
            service.renew(uuid.uuid4(), loan.id)

    def test_unknown_borrowing_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.renew(uuid.uuid4(), uuid.uuid4())


class TestNotifyOverdue:
    def test_sends_one_reminder_per_overdue_borrowing(
        self, service, borrowing_repository, notifier
    ):
        user_id = uuid.uuid4()
        past = datetime.now(UTC) - timedelta(days=20)
        borrowing_repository.create(
            {
                "user_id": user_id,
                "book_id": uuid.uuid4(),
                "borrowed_at": past,
                "due_date": past + timedelta(days=14),
                "returned_at": None,
            }
        )

        sent = asyncio.run(service.notify_overdue())

        assert sent == 1
        assert len(notifier.sent_to(user_id)) == 1

    def test_no_overdue_borrowings_sends_nothing(self, service):
        assert asyncio.run(service.notify_overdue()) == 0
