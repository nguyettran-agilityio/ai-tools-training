"""Borrowing Pydantic DTOs (request/response schemas). `status` is a
`@computed_field` derived from `returned_at`/`due_date`, never a stored field.
"""

# Standard library
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

# Third-party
from pydantic import computed_field

# Local application
# core
from app.core.schemas import CamelModel

# reservation
from app.modules.reservation.schemas import ReservationRead


class BorrowingStatus(StrEnum):
    ACTIVE = "active"
    RETURNED = "returned"
    OVERDUE = "overdue"


class BorrowRequest(CamelModel):
    book_id: uuid.UUID


class OverdueNotifyResult(CamelModel):
    reminders_sent: int


class BorrowingRead(CamelModel):
    id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    borrowed_at: datetime
    due_date: datetime
    returned_at: datetime | None

    # Datetimes here are assumed UTC-aware — naive-vs-aware normalization
    # happens once in `mappers.py::to_borrowing_read`, not this schema.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> BorrowingStatus:
        if self.returned_at is not None:
            return BorrowingStatus.RETURNED
        if self.due_date < datetime.now(UTC):
            return BorrowingStatus.OVERDUE
        return BorrowingStatus.ACTIVE


class BorrowOutcome(StrEnum):
    BORROWED = "borrowed"
    RESERVED = "reserved"


@dataclass
class BorrowResult:
    kind: BorrowOutcome
    borrowing: BorrowingRead | None = None
    reservation: ReservationRead | None = None
