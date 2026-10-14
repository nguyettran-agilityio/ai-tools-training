"""Unit tests for `CategoryService` against `FakeCategoryRepository` — no
database, no session, no `TestClient`. Compare with
`tests/test_categories.py` (same behavior, through the real HTTP API + DB).
"""

# Standard library
import uuid
from unittest.mock import create_autospec

# Third-party
import pytest

# Local application
from app.core.exceptions import ConflictError, NotFoundError
from app.core.schemas import PaginationParams
from app.modules.book.repositories import BookRepositoryInterface
from app.modules.category.schemas import CategoryCreate, CategoryUpdate
from app.modules.category.services import CategoryService
from tests.fakes import FakeCategoryRepository


@pytest.fixture
def category_repository():
    return FakeCategoryRepository()


@pytest.fixture
def book_repository():
    repository = create_autospec(BookRepositoryInterface, instance=True)
    repository.count_by_category.return_value = 0
    return repository


@pytest.fixture
def service(category_repository, book_repository):
    return CategoryService(category_repository, book_repository)


class TestCreate:
    def test_creates_and_returns_a_dto(self, service):
        result = service.create(CategoryCreate(name="Fiction"))

        assert result.id is not None
        assert result.name == "Fiction"

    def test_duplicate_name_raises_conflict(self, service):
        service.create(CategoryCreate(name="Fiction"))

        with pytest.raises(ConflictError):
            service.create(CategoryCreate(name="Fiction"))


class TestUpdate:
    def test_partial_update_keeps_untouched_fields(self, service):
        created = service.create(CategoryCreate(name="Fiction"))

        updated = service.update(created.id, CategoryUpdate(description="Fiction books"))

        assert updated.name == "Fiction"
        assert updated.description == "Fiction books"

    def test_missing_category_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.update(uuid.uuid4(), CategoryUpdate(description="x"))

    def test_rename_to_existing_name_raises_conflict(self, service):
        service.create(CategoryCreate(name="Fiction"))
        other = service.create(CategoryCreate(name="History"))

        with pytest.raises(ConflictError):
            service.update(other.id, CategoryUpdate(name="Fiction"))


class TestDelete:
    def test_deletes_when_no_book_references_it(self, service, category_repository):
        created = service.create(CategoryCreate(name="Fiction"))

        service.delete(created.id)

        assert category_repository.get_by_id(created.id) is None

    def test_refuses_when_a_book_still_references_it(self, service, book_repository):
        created = service.create(CategoryCreate(name="Fiction"))
        book_repository.count_by_category.return_value = 2

        with pytest.raises(ConflictError):
            service.delete(created.id)

    def test_missing_category_raises_not_found(self, service):
        with pytest.raises(NotFoundError):
            service.delete(uuid.uuid4())


class TestList:
    def test_pages_through_created_categories(self, service):
        for name in ("Fiction", "Sci-Fi", "History"):
            service.create(CategoryCreate(name=name))

        page = service.list(PaginationParams(page=1, page_size=2))

        assert page.total == 3
        assert len(page.items) == 2
        assert page.total_pages == 2
