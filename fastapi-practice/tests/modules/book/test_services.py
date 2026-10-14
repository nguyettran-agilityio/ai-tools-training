"""Unit tests for `BookService` against `FakeBookRepository` — no database,
no session, no `TestClient`. Compare with `tests/test_books.py` (same
behavior, through the real HTTP API + DB).
"""

# Standard library
import uuid
from unittest.mock import create_autospec

# Third-party
import pytest

# Local application
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.schemas import PaginationParams
from app.modules.book.schemas import BookCreate, BookUpdate
from app.modules.book.services import BookService
from app.modules.borrowing.repositories import BorrowingRepositoryInterface
from app.modules.category.repositories import CategoryRepositoryInterface
from app.modules.reservation.repositories import ReservationRepositoryInterface
from tests.fakes import FakeBookRepository

_CATEGORY_ID = uuid.uuid4()


@pytest.fixture
def book_repository():
    return FakeBookRepository()


@pytest.fixture
def category_repository():
    repository = create_autospec(CategoryRepositoryInterface, instance=True)
    repository.get_by_id.return_value = object()  # any non-None value means "exists"
    return repository


@pytest.fixture
def borrowing_repository():
    repository = create_autospec(BorrowingRepositoryInterface, instance=True)
    repository.count_active_by_book.return_value = 0
    return repository


@pytest.fixture
def reservation_repository():
    repository = create_autospec(ReservationRepositoryInterface, instance=True)
    repository.count_open_by_book.return_value = 0
    return repository


@pytest.fixture
def service(book_repository, category_repository, borrowing_repository, reservation_repository):
    return BookService(
        book_repository, category_repository, borrowing_repository, reservation_repository
    )


def _new_book(isbn: str = "9780000000000", **overrides) -> BookCreate:
    data = {
        "title": "Deep Work",
        "author": "Cal Newport",
        "isbn": isbn,
        "category_id": _CATEGORY_ID,
        "total_copies": 3,
    }
    data.update(overrides)
    return BookCreate(**data)


class TestCreate:
    def test_creates_with_available_copies_equal_to_total(self, service):
        result = service.create(_new_book())

        assert result.total_copies == 3
        assert result.available_copies == 3

    def test_unknown_category_raises_not_found(self, service, category_repository):
        category_repository.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            service.create(_new_book())

    def test_duplicate_isbn_raises_conflict(self, service):
        service.create(_new_book(isbn="9780000000001"))

        with pytest.raises(ConflictError):
            service.create(_new_book(isbn="9780000000001"))


class TestUpdate:
    def test_partial_update_keeps_untouched_fields(self, service):
        created = service.create(_new_book())

        updated = service.update(created.id, BookUpdate(title="Deep Work 2nd Edition"))

        assert updated.title == "Deep Work 2nd Edition"
        assert updated.author == "Cal Newport"

    def test_missing_book_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.update(uuid.uuid4(), BookUpdate(title="X"))

    def test_rename_to_existing_isbn_raises_conflict(self, service):
        service.create(_new_book(isbn="9780000000001"))
        other = service.create(_new_book(isbn="9780000000002"))

        with pytest.raises(ConflictError):
            service.update(other.id, BookUpdate(isbn="9780000000001"))

    def test_new_category_must_exist(self, service, category_repository):
        created = service.create(_new_book())
        category_repository.get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            service.update(created.id, BookUpdate(category_id=uuid.uuid4()))

    def test_increasing_total_copies_increases_available_by_the_same_amount(self, service):
        created = service.create(_new_book(total_copies=3))

        updated = service.update(created.id, BookUpdate(total_copies=5))

        assert updated.total_copies == 5
        assert updated.available_copies == 5

    def test_decreasing_total_copies_preserves_borrowed_count(self, service, book_repository):
        created = service.create(_new_book(total_copies=3))
        book_repository.try_decrement_available_copies(created.id)  # 1 now borrowed

        updated = service.update(created.id, BookUpdate(total_copies=2))

        assert updated.total_copies == 2
        assert updated.available_copies == 1  # 2 - 1 borrowed, preserved

    def test_total_copies_below_borrowed_count_raises_bad_request(self, service, book_repository):
        created = service.create(_new_book(total_copies=3))
        book_repository.try_decrement_available_copies(created.id)
        book_repository.try_decrement_available_copies(created.id)  # 2 now borrowed

        with pytest.raises(BadRequestError):
            service.update(created.id, BookUpdate(total_copies=1))


class TestDelete:
    def test_deletes_when_no_active_borrowings(self, service, book_repository):
        created = service.create(_new_book())

        service.delete(created.id)

        assert book_repository.get_by_id(created.id) is None

    def test_refuses_when_active_borrowings_exist(self, service, borrowing_repository):
        created = service.create(_new_book())
        borrowing_repository.count_active_by_book.return_value = 1

        with pytest.raises(ConflictError):
            service.delete(created.id)

    def test_refuses_when_open_reservations_exist(self, service, reservation_repository):
        created = service.create(_new_book())
        reservation_repository.count_open_by_book.return_value = 1

        with pytest.raises(ConflictError):
            service.delete(created.id)

    def test_missing_book_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.delete(uuid.uuid4())


class TestList:
    def test_pages_through_created_books(self, service):
        for i in range(3):
            service.create(_new_book(isbn=f"978000000000{i}"))

        page = service.list(None, None, False, PaginationParams(page=1, page_size=2))

        assert page.total == 3
        assert len(page.items) == 2
