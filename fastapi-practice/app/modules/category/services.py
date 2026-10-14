# Standard library
import uuid
from typing import cast

# Local application
# core
from app.core.exceptions import AlreadyExistsError, ConflictError
from app.core.mappers import pagination_offset, to_page
from app.core.schemas import Page, PaginationParams
from app.core.service_utils import get_or_404

# book
from app.modules.book.repositories import BookRepositoryInterface

# category
from app.modules.category.repositories import CategoryRepositoryInterface, CategoryUpdateFields
from app.modules.category.schemas import CategoryCreate, CategoryRead, CategoryUpdate


class CategoryService:
    def __init__(
        self,
        category_repository: CategoryRepositoryInterface,
        book_repository: BookRepositoryInterface,
    ) -> None:
        self.category_repository = category_repository
        self.book_repository = book_repository

    def list(self, pagination: PaginationParams) -> Page[CategoryRead]:
        """Paginated category listing."""
        offset = pagination_offset(pagination.page, pagination.page_size)
        items, total = self.category_repository.list(offset, pagination.page_size)
        # No mapper_fn: the repository already returns `CategoryRead`.
        return to_page(items, total, pagination.page, pagination.page_size)

    def get(self, category_id: uuid.UUID) -> CategoryRead:
        """Fetch a single category by id, or raise `NotFoundError`."""
        return get_or_404(self.category_repository, category_id, "Category not found")

    def create(self, data: CategoryCreate) -> CategoryRead:
        """Create a category; 409s if the name is already taken."""
        if self.category_repository.get_by_name(data.name) is not None:
            raise AlreadyExistsError("Category name already exists")

        return self.category_repository.create(data.model_dump())

    def update(self, category_id: uuid.UUID, data: CategoryUpdate) -> CategoryRead:
        """Partial update; 409s if renaming to a name already used by another category."""
        category = get_or_404(self.category_repository, category_id, "Category not found")

        updates = cast(CategoryUpdateFields, data.model_dump(exclude_unset=True))

        new_name = updates.get("name")
        if new_name is not None and new_name != category.name:
            existing = self.category_repository.get_by_name(new_name)
            if existing is not None and existing.id != category_id:
                raise AlreadyExistsError("Category name already exists")

        return self.category_repository.update(category_id, updates)

    def delete(self, category_id: uuid.UUID) -> None:
        """Delete a category; 409s if any book still references it."""
        get_or_404(self.category_repository, category_id, "Category not found")

        book_count = self.book_repository.count_by_category(category_id)
        if book_count > 0:
            raise ConflictError(f"Category is in use by {book_count} book(s) and cannot be deleted")

        self.category_repository.delete(category_id)
