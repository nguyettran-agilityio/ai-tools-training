"""Borrowing mappers: model -> read schema. No Create/Update-to-model logic here —
that's the service layer's job (a later epic)."""

# Standard library
from datetime import UTC, datetime

# Local application
# borrowing
from app.modules.borrowing.models import Borrowing
from app.modules.borrowing.schemas import BorrowingRead


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite round-trips datetimes as naive; reattach UTC so `BorrowingRead.status`
    can compare against an aware `datetime.now(UTC)` without raising."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def to_borrowing_read(borrowing: Borrowing) -> BorrowingRead:
    # `BorrowingRead.status` is a @computed_field derived from
    # returned_at/due_date, so it picks up the UTC-normalized values below
    # once validation runs.
    return BorrowingRead.model_validate(
        {
            "id": borrowing.id,
            "user_id": borrowing.user_id,
            "book_id": borrowing.book_id,
            "borrowed_at": _as_utc(borrowing.borrowed_at),
            "due_date": _as_utc(borrowing.due_date),
            "returned_at": _as_utc(borrowing.returned_at),
            "renewed_at": _as_utc(borrowing.renewed_at),
        }
    )
