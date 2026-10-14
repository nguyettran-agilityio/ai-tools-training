"""Borrowing repository interface — zero ORM imports. Concrete implementation
lives in `repositories_sqlmodel.py`; services depend only on this interface.
"""

# Standard library
import abc
import uuid
from datetime import datetime
from typing import TypedDict

# Local application
# core
from app.core.repository_interface import CrudRepositoryInterface

# borrowing
from app.modules.borrowing.schemas import BorrowingRead


class BorrowingUpdateFields(TypedDict, total=False):
    """The only field `update()` is ever asked to change — via `mark_returned`,
    the sole write transition a borrowing supports."""

    returned_at: datetime | None


class BorrowingRepositoryInterface(CrudRepositoryInterface[BorrowingRead, BorrowingUpdateFields]):
    @abc.abstractmethod
    def list_active_by_user(self, user_id: uuid.UUID) -> list[BorrowingRead]: ...

    @abc.abstractmethod
    def count_active_by_user(self, user_id: uuid.UUID) -> int: ...

    @abc.abstractmethod
    def get_active_by_user_and_book(
        self, user_id: uuid.UUID, book_id: uuid.UUID
    ) -> BorrowingRead | None: ...

    @abc.abstractmethod
    def list_by_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[BorrowingRead], int]: ...

    @abc.abstractmethod
    def list_all(
        self,
        offset: int,
        limit: int,
        overdue_only: bool = False,
        now: datetime | None = None,
    ) -> tuple[list[BorrowingRead], int]: ...

    @abc.abstractmethod
    def count_active_by_book(self, book_id: uuid.UUID) -> int: ...

    @abc.abstractmethod
    def mark_returned(self, id: uuid.UUID, returned_at: datetime) -> BorrowingRead:
        """The one write transition a borrowing ever makes."""
        ...
