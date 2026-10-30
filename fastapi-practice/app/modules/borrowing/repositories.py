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
    """Every field `update()` is ever asked to change — via the 2 named write
    transitions below (`mark_returned`, `mark_renewed`)."""

    returned_at: datetime | None
    due_date: datetime
    renewed_at: datetime | None


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
    def list_late_returns(
        self,
        offset: int,
        limit: int,
        returned_from: datetime | None = None,
        returned_to: datetime | None = None,
    ) -> tuple[list[BorrowingRead], int]:
        """Loans returned after their due date, newest return first. Both
        bounds are inclusive and expected UTC-aware; `None` = no bound."""
        ...

    @abc.abstractmethod
    def count_active_by_book(self, book_id: uuid.UUID) -> int: ...

    # The 2 write transitions a borrowing ever makes — named rather than a
    # generic `update(id, dict)`.
    @abc.abstractmethod
    def mark_returned(self, id: uuid.UUID, returned_at: datetime) -> BorrowingRead: ...

    @abc.abstractmethod
    def mark_renewed(
        self, id: uuid.UUID, due_date: datetime, renewed_at: datetime
    ) -> BorrowingRead:
        """Plain update, not a conditional `WHERE renewed_at IS NULL`: two
        concurrent renew requests can both pass the service's "already
        renewed" check and both write. Accepted limitation — the second write
        sets the same `due_date`, so the loan is still extended only once."""
        ...
