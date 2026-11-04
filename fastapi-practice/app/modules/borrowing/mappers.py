"""Borrowing mappers: model -> read schema. No Create/Update-to-model logic here —
that's the service layer's job (a later epic)."""

# Standard library
from datetime import UTC, datetime

# Local application
# borrowing
from app.modules.borrowing.models import Borrowing, BorrowingBan
from app.modules.borrowing.schemas import BorrowingBanRead, BorrowingRead


def _as_utc(value: datetime | None) -> datetime | None:
    """Guarantee an aware UTC value so `BorrowingRead.status` can compare
    against `datetime.now(UTC)` without raising. Columns loaded from the DB
    already come back aware via `UTCDateTime` (`app/core/db_types.py`); this
    only matters for a naive value set on a model that was never reloaded."""
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


def to_borrowing_ban_read(ban: BorrowingBan) -> BorrowingBanRead:
    return BorrowingBanRead.model_validate(
        {
            "user_id": ban.user_id,
            "banned_until": _as_utc(ban.banned_until),
            "source_borrowing_id": ban.source_borrowing_id,
            "created_at": _as_utc(ban.created_at),
            "updated_at": _as_utc(ban.updated_at),
        }
    )
