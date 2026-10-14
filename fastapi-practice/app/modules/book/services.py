# Standard library
import uuid
from typing import cast

# Local application
# core
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.mappers import pagination_offset, to_page
from app.core.schemas import Page, PaginationParams
from app.core.service_utils import get_or_404

# book
from app.modules.book.repositories import BookRepositoryInterface, BookUpdateFields
from app.modules.book.schemas import BookCreate, BookRead, BookUpdate

# borrowing
from app.modules.borrowing.repositories import BorrowingRepositoryInterface

# category
from app.modules.category.repositories import CategoryRepositoryInterface

# reservation
from app.modules.reservation.repositories import ReservationRepositoryInterface


class BookService:
    def __init__(
        self,
        book_repository: BookRepositoryInterface,
        category_repository: CategoryRepositoryInterface,
        borrowing_repository: BorrowingRepositoryInterface,
        reservation_repository: ReservationRepositoryInterface,
    ) -> None:
        self.book_repository = book_repository
        self.category_repository = category_repository
        self.borrowing_repository = borrowing_repository
        self.reservation_repository = reservation_repository

    def list(
        self,
        query: str | None,
        category_id: uuid.UUID | None,
        available_only: bool,
        pagination: PaginationParams,
    ) -> Page[BookRead]:
        """Paginated book search, optionally filtered by text query, category, availability."""
        offset = pagination_offset(pagination.page, pagination.page_size)
        items, total = self.book_repository.search(
            query, category_id, offset, pagination.page_size, available_only
        )
        # No mapper_fn: the repository already returns `BookRead`.
        return to_page(items, total, pagination.page, pagination.page_size)

    def get(self, book_id: uuid.UUID) -> BookRead:
        """Fetch a single book by id, or raise `NotFoundError`."""
        return get_or_404(self.book_repository, book_id, "Book not found")

    def create(self, data: BookCreate) -> BookRead:
        """Create a book; `available_copies` starts equal to `total_copies`."""
        if self.category_repository.get_by_id(data.category_id) is None:
            raise NotFoundError("Category not found")

        if self.book_repository.get_by_isbn(data.isbn) is not None:
            raise ConflictError("ISBN already exists")

        return self.book_repository.create(
            {
                "title": data.title,
                "author": data.author,
                "isbn": data.isbn,
                "description": data.description,
                "category_id": data.category_id,
                "total_copies": data.total_copies,
                "available_copies": data.total_copies,
            }
        )

    def update(self, book_id: uuid.UUID, data: BookUpdate) -> BookRead:
        """Partial update; validates a changed `category_id`/`isbn`, and rejects a
        `total_copies` drop below the currently-borrowed count."""
        book = get_or_404(self.book_repository, book_id, "Book not found")

        updates = cast(BookUpdateFields, data.model_dump(exclude_unset=True))

        new_category_id = updates.get("category_id")
        if new_category_id is not None and new_category_id != book.category_id:
            if self.category_repository.get_by_id(new_category_id) is None:
                raise NotFoundError("Category not found")

        new_isbn = updates.get("isbn")
        if new_isbn is not None and new_isbn != book.isbn:
            existing = self.book_repository.get_by_isbn(new_isbn)
            if existing is not None and existing.id != book_id:
                raise ConflictError("ISBN already exists")

        new_total_copies = updates.get("total_copies")
        if new_total_copies is not None and new_total_copies != book.total_copies:
            borrowed = book.total_copies - book.available_copies
            if new_total_copies < borrowed:
                raise BadRequestError(
                    f"Total copies cannot be less than currently borrowed copies ({borrowed})"
                )
            updates["available_copies"] = new_total_copies - borrowed

        return self.book_repository.update(book_id, updates)

    def delete(self, book_id: uuid.UUID) -> None:
        """Delete a book; 409s if it still has active borrowings or open reservations."""
        get_or_404(self.book_repository, book_id, "Book not found")

        active_count = self.borrowing_repository.count_active_by_book(book_id)
        if active_count > 0:
            raise ConflictError(
                f"Book has {active_count} active borrowing(s) and cannot be deleted"
            )

        reservation_count = self.reservation_repository.count_open_by_book(book_id)
        if reservation_count > 0:
            raise ConflictError(
                f"Book has {reservation_count} open reservation(s) and cannot be deleted"
            )

        self.book_repository.delete(book_id)
