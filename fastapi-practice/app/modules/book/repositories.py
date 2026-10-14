"""Book repository interface — zero ORM imports. Concrete implementation
lives in `repositories_sqlmodel.py`; services depend only on this interface.
"""

# Standard library
import abc
import uuid
from typing import TypedDict

# Local application
# core
from app.core.repository_interface import CrudRepositoryInterface

# book
from app.modules.book.schemas import BookRead


class BookUpdateFields(TypedDict, total=False):
    """Every field `update()` may be asked to change. `available_copies` is
    here even though `BookUpdate` (the client-facing schema) never exposes
    it — `BookService.update()` computes it itself when `total_copies` changes."""

    title: str
    author: str
    isbn: str
    description: str | None
    category_id: uuid.UUID
    total_copies: int
    available_copies: int


class BookRepositoryInterface(CrudRepositoryInterface[BookRead, BookUpdateFields]):
    @abc.abstractmethod
    def get_by_isbn(self, isbn: str) -> BookRead | None: ...

    @abc.abstractmethod
    def search(
        self,
        query: str | None,
        category_id: uuid.UUID | None,
        offset: int,
        limit: int,
        available_only: bool = False,
    ) -> tuple[list[BookRead], int]:
        """Filter by title-or-author, category, and/or availability, combinable."""
        ...

    @abc.abstractmethod
    def count_by_category(self, category_id: uuid.UUID) -> int: ...

    @abc.abstractmethod
    def try_decrement_available_copies(self, book_id: uuid.UUID) -> bool:
        """Atomically claim one copy; returns whether one was actually claimed."""
        ...

    @abc.abstractmethod
    def increment_available_copies(self, book_id: uuid.UUID) -> None:
        """Atomically give one copy back, capped at `total_copies`."""
        ...
