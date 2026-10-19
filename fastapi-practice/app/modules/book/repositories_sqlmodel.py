"""SQLModel-backed concrete `BookRepositoryInterface` — the only file in
this module allowed to import `Book` or `sqlmodel` itself.
"""

# Standard library
import uuid

# Third-party
from sqlmodel import func, or_, select, update

# Local application
# core
from app.core.repository_sqlmodel import SQLModelBackend, apply_filters

# book
from app.modules.book.mappers import to_book_read
from app.modules.book.models import Book
from app.modules.book.repositories import BookRepositoryInterface, BookUpdateFields
from app.modules.book.schemas import BookRead


class BookRepository(BookRepositoryInterface):
    # Narrows the inherited `backend: CrudBackend[Any, ReadT, UpdateT]` to the
    # concrete SQLModel type for this file only, so mypy knows
    # `self.backend.session` exists here without leaking that knowledge
    # into the ORM-agnostic interface.
    backend: SQLModelBackend[Book, BookRead, BookUpdateFields]

    def get_by_isbn(self, isbn: str) -> BookRead | None:
        book = self.backend.session.exec(select(Book).where(Book.isbn == isbn)).first()
        return to_book_read(book) if book is not None else None

    def search(
        self,
        query: str | None,
        category_id: uuid.UUID | None,
        offset: int,
        limit: int,
        available_only: bool = False,
    ) -> tuple[list[BookRead], int]:
        """Total is a real SELECT COUNT against the same filters, not `len()`."""
        count_stmt, list_stmt = apply_filters(
            select(func.count()).select_from(Book),
            select(Book),
            [
                (
                    or_(Book.title.ilike(f"%{query}%"), Book.author.ilike(f"{query}%"))
                    if query
                    else None
                ),
                Book.category_id == category_id if category_id is not None else None,
                Book.available_copies > 0 if available_only else None,
            ],
        )

        total = self.backend.session.exec(count_stmt).one()
        items = self.backend.session.exec(list_stmt.offset(offset).limit(limit)).all()
        return [to_book_read(item) for item in items], total

    def count_by_category(self, category_id: uuid.UUID) -> int:
        return self.backend.session.exec(
            select(func.count()).select_from(Book).where(Book.category_id == category_id)
        ).one()

    def try_decrement_available_copies(self, book_id: uuid.UUID) -> bool:
        """Atomically claim one copy via a single conditional UPDATE (the
        `available_copies > 0` guard runs in the same statement, not a
        prior read) — safe under concurrent callers racing for the last copy."""
        result = self.backend.session.exec(
            update(Book)
            .where(Book.id == book_id, Book.available_copies > 0)
            .values(available_copies=Book.available_copies - 1)
        )
        self.backend.session.flush()
        return result.rowcount > 0

    def increment_available_copies(self, book_id: uuid.UUID) -> None:
        """Atomically give one copy back, capped at `total_copies`."""
        self.backend.session.exec(
            update(Book)
            .where(Book.id == book_id)
            .values(available_copies=func.min(Book.available_copies + 1, Book.total_copies))
        )
        self.backend.session.flush()
