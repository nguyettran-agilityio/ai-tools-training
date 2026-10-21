"""Reservation repository interface — zero ORM imports. Concrete implementation
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

# reservation
from app.modules.reservation.enums import ReservationStatus
from app.modules.reservation.schemas import ReservationRead


class ReservationUpdateFields(TypedDict, total=False):
    """Every field `update()` is ever asked to change — via the 3 named
    status-transition methods below, never an arbitrary field-set."""

    status: ReservationStatus
    notified_at: datetime | None


class ReservationRepositoryInterface(
    CrudRepositoryInterface[ReservationRead, ReservationUpdateFields]
):
    @abc.abstractmethod
    def list_pending_for_book(self, book_id: uuid.UUID) -> list[ReservationRead]: ...

    @abc.abstractmethod
    def get_open_by_user_and_book(
        self, user_id: uuid.UUID, book_id: uuid.UUID
    ) -> ReservationRead | None:
        """Pending or notified — both mean "still waiting on this book"."""
        ...

    @abc.abstractmethod
    def list_by_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[ReservationRead], int]: ...

    @abc.abstractmethod
    def count_open_by_book(self, book_id: uuid.UUID) -> int:
        """Pending or notified reservations still waiting on this book."""
        ...

    @abc.abstractmethod
    def count_open_by_book_excluding_user(self, book_id: uuid.UUID, user_id: uuid.UUID) -> int:
        """Pending or notified reservations on this book held by anyone other
        than `user_id` — i.e. other members still waiting on it."""
        ...

    @abc.abstractmethod
    def count_open_by_user(self, user_id: uuid.UUID) -> int:
        """Pending or notified reservations still open for this user."""
        ...

    # The 3 write transitions a reservation ever makes — named rather than
    # a generic `update(id, dict)`, since each is a specific, well-defined
    # status flip, never an arbitrary field-set.
    @abc.abstractmethod
    def mark_cancelled(self, id: uuid.UUID) -> ReservationRead: ...

    @abc.abstractmethod
    def mark_notified(self, id: uuid.UUID, notified_at: datetime) -> ReservationRead: ...

    @abc.abstractmethod
    def mark_fulfilled(self, id: uuid.UUID) -> ReservationRead: ...
