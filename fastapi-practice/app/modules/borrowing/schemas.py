"""Borrowing Pydantic DTOs (request/response schemas). `status` is a
`@computed_field` derived from `returned_at`/`due_date`, never a stored field.
"""

# Standard library
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Annotated, Any

# Third-party
from pydantic import BeforeValidator, computed_field

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
    renewed_at: datetime | None = None

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


class BorrowingReportRow(BorrowingRead):
    """Overdue + late-returns report row: every `BorrowingRead` field
    (including the computed `status`) plus the member's email and the book
    title. Both are non-null — borrowings cascade on user/book delete."""

    user_email: str
    book_title: str


_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _date_only_to_end_of_day(value: Any) -> Any:
    """A date-only upper bound (`to=2026-11-01`) means the whole of that day
    in UTC. Checked on the raw string: once parsed, `2026-11-01` and
    `2026-11-01T00:00:00` are the same datetime. Anything else passes through
    to the normal datetime parsing (and its 422 on bad input)."""
    if isinstance(value, str) and _DATE_ONLY.match(value):
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return value
        return datetime.combine(day, time.max, tzinfo=UTC)
    return value


ReportUpperBound = Annotated[datetime, BeforeValidator(_date_only_to_end_of_day)]


class BorrowOutcome(StrEnum):
    BORROWED = "borrowed"
    RESERVED = "reserved"


@dataclass
class BorrowResult:
    kind: BorrowOutcome
    borrowing: BorrowingRead | None = None
    reservation: ReservationRead | None = None
