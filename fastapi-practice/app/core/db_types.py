"""Column types shared by every module's table models."""

# Standard library
from datetime import UTC, datetime
from typing import Any

# Third-party
from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """A plain `DateTime` column that always stores naive UTC and always
    reads back aware UTC.

    Neither backend keeps the offset of an aware value in a `DateTime`
    column: SQLite drops it without converting (a `+07:00` value is stored as
    local time), and Postgres `timestamp` converts it to the *session* time
    zone first. Converting to naive UTC before the driver sees it makes the
    stored value independent of both, and also covers query parameters
    compared against these columns. A naive value is taken to be UTC already.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        stored: datetime = value
        if stored.tzinfo is None:
            return stored.replace(tzinfo=UTC)
        return stored.astimezone(UTC)
