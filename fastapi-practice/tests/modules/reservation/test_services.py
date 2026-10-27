"""Unit tests for `ReservationService` against fake repositories — no
database, no session, no `TestClient`. Compare with
`tests/test_reservations.py` (same behavior, through the real HTTP API + DB).
"""

# Standard library
import asyncio
import uuid

# Third-party
import pytest

# Local application
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.notifications import InMemoryNotifier
from app.core.schemas import PaginationParams
from app.modules.reservation.schemas import ReservationCreate
from app.modules.reservation.services import ReservationService
from tests.fakes import FakeBookRepository, FakeReservationRepository, FakeUserRepository


@pytest.fixture
def book_repository():
    return FakeBookRepository()


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
def service(reservation_repository, book_repository, user_repository, notifier):
    return ReservationService(reservation_repository, book_repository, user_repository, notifier)


def _make_book(book_repository):
    return book_repository.create(
        {
            "title": "Deep Work",
            "author": "Cal Newport",
            "isbn": f"isbn-{uuid.uuid4()}",
            "category_id": uuid.uuid4(),
            "total_copies": 1,
            "available_copies": 0,
        }
    )


class TestCreate:
    def test_creates_a_pending_reservation(self, service, book_repository):
        book = _make_book(book_repository)
        user_id = uuid.uuid4()

        result = service.create(user_id, ReservationCreate(book_id=book.id))

        assert result.status == "pending"
        assert result.user_id == user_id

    def test_unknown_book_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.create(uuid.uuid4(), ReservationCreate(book_id=uuid.uuid4()))

    def test_second_open_reservation_for_the_same_book_raises_conflict(
        self, service, book_repository
    ):
        book = _make_book(book_repository)
        user_id = uuid.uuid4()
        service.create(user_id, ReservationCreate(book_id=book.id))

        with pytest.raises(ConflictError):
            service.create(user_id, ReservationCreate(book_id=book.id))


class TestCancel:
    def test_cancels_the_callers_own_pending_reservation(self, service, book_repository):
        book = _make_book(book_repository)
        user_id = uuid.uuid4()
        reservation = service.create(user_id, ReservationCreate(book_id=book.id))

        service.cancel(user_id, reservation.id)

        assert reservation_status(service, reservation.id) == "cancelled"

    def test_missing_reservation_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.cancel(uuid.uuid4(), uuid.uuid4())

    def test_cancelling_someone_elses_reservation_raises_forbidden(self, service, book_repository):
        book = _make_book(book_repository)
        owner = uuid.uuid4()
        reservation = service.create(owner, ReservationCreate(book_id=book.id))

        with pytest.raises(ForbiddenError):
            service.cancel(uuid.uuid4(), reservation.id)

    def test_cancelling_an_already_cancelled_reservation_raises_conflict(
        self, service, book_repository
    ):
        book = _make_book(book_repository)
        user_id = uuid.uuid4()
        reservation = service.create(user_id, ReservationCreate(book_id=book.id))
        service.cancel(user_id, reservation.id)

        with pytest.raises(ConflictError):
            service.cancel(user_id, reservation.id)


class TestMyReservations:
    def test_pages_through_the_callers_own_reservations(self, service, book_repository):
        user_id = uuid.uuid4()
        for _ in range(3):
            service.create(user_id, ReservationCreate(book_id=_make_book(book_repository).id))

        page = service.my_reservations(user_id, PaginationParams(page=1, page_size=2))

        assert page.total == 3
        assert len(page.items) == 2


class TestNotifyBookAvailable:
    def test_notifies_every_pending_reserver_and_marks_them_notified(
        self, service, book_repository, notifier
    ):
        book = _make_book(book_repository)
        user_a, user_b = uuid.uuid4(), uuid.uuid4()
        service.create(user_a, ReservationCreate(book_id=book.id))
        # A 2nd reservation for the same book, different user — bypasses the
        # "one open reservation per user per book" rule `create()` enforces,
        # since the FIFO queue is naturally multi-user.
        reservation_b = service.reservation_repository.create(
            {"user_id": user_b, "book_id": book.id}
        )

        count = asyncio.run(service.notify_book_available(book.id))

        assert count == 2
        assert len(notifier.sent_to(user_a)) == 1
        assert len(notifier.sent_to(user_b)) == 1
        assert reservation_status(service, reservation_b.id) == "notified"

    def test_no_pending_reservations_returns_zero(self, service):
        assert asyncio.run(service.notify_book_available(uuid.uuid4())) == 0


def reservation_status(service: ReservationService, reservation_id: uuid.UUID) -> str:
    reservation = service.reservation_repository.get_by_id(reservation_id)
    assert reservation is not None
    return reservation.status
