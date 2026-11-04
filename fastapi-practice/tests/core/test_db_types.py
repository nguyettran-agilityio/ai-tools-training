"""`UTCDateTime` tests: unit tests on the type, plus a round-trip through the
`db_engine` fixture (SQLite by default, Postgres when `TEST_DATABASE_URL` is
set)."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import Session

from app.core.db_types import UTCDateTime
from app.modules.category.models import Category

PLUS_7 = timezone(timedelta(hours=7))


class TestBindParam:
    def test_aware_value_is_converted_to_naive_utc(self):
        value = datetime(2026, 11, 4, 9, 0, tzinfo=PLUS_7)

        bound = UTCDateTime().process_bind_param(value, sqlite.dialect())

        assert bound == datetime(2026, 11, 4, 2, 0)
        assert bound is not None and bound.tzinfo is None

    def test_naive_value_is_kept_as_utc(self):
        value = datetime(2026, 11, 4, 9, 0)

        assert UTCDateTime().process_bind_param(value, postgresql.dialect()) == value

    def test_none_stays_none(self):
        assert UTCDateTime().process_bind_param(None, sqlite.dialect()) is None


class TestResultValue:
    def test_naive_value_reads_back_as_aware_utc(self):
        result = UTCDateTime().process_result_value(datetime(2026, 11, 4, 2, 0), sqlite.dialect())

        assert result == datetime(2026, 11, 4, 2, 0, tzinfo=UTC)
        assert result is not None and result.tzinfo is UTC

    def test_none_stays_none(self):
        assert UTCDateTime().process_result_value(None, sqlite.dialect()) is None


def test_non_utc_value_round_trips_as_the_same_instant(db_engine):
    """Regression: a `+07:00` value used to be stored as local time (SQLite
    dropped the offset without converting). It must come back as the same
    instant, in UTC."""
    written = datetime(2026, 11, 4, 9, 0, tzinfo=PLUS_7)
    with Session(db_engine) as session:
        category = Category(name="Round trip", created_at=written)
        session.add(category)
        session.commit()
        category_id = category.id

    with Session(db_engine) as session:
        read = session.get(Category, category_id)

    assert read is not None
    assert read.created_at == written
    assert read.created_at == datetime(2026, 11, 4, 2, 0, tzinfo=UTC)
    assert read.created_at.tzinfo is UTC
