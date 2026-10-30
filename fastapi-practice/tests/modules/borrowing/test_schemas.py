"""Borrowing schema computed-field tests. No DB involved."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from app.modules.borrowing.schemas import BorrowingRead, BorrowingStatus, ReportUpperBound


class TestBorrowingReadStatus:
    def _make(self, *, due_date: datetime, returned_at: datetime | None) -> BorrowingRead:
        return BorrowingRead(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            book_id=uuid.uuid4(),
            borrowed_at=datetime.now(UTC) - timedelta(days=1),
            due_date=due_date,
            returned_at=returned_at,
        )

    def test_future_due_date_and_not_returned_is_active(self):
        borrowing = self._make(due_date=datetime.now(UTC) + timedelta(days=5), returned_at=None)
        assert borrowing.status == BorrowingStatus.ACTIVE

    def test_past_due_date_and_not_returned_is_overdue(self):
        borrowing = self._make(due_date=datetime.now(UTC) - timedelta(days=1), returned_at=None)
        assert borrowing.status == BorrowingStatus.OVERDUE

    def test_returned_is_returned_regardless_of_due_date(self):
        borrowing = self._make(
            due_date=datetime.now(UTC) - timedelta(days=1),
            returned_at=datetime.now(UTC),
        )
        assert borrowing.status == BorrowingStatus.RETURNED


class TestReportUpperBound:
    """A date-only `to` covers the whole day in UTC (BA decision replacing
    Dev Q2 on #42); anything else parses as a normal datetime."""

    adapter = TypeAdapter(ReportUpperBound)

    def test_date_only_means_end_of_that_day_utc(self):
        assert self.adapter.validate_python("2026-11-01") == datetime(
            2026, 11, 1, 23, 59, 59, 999999, tzinfo=UTC
        )

    def test_explicit_midnight_is_unchanged(self):
        assert self.adapter.validate_python("2026-11-01T00:00:00") == datetime(2026, 11, 1)

    def test_offset_is_kept_for_the_service_to_convert(self):
        value = self.adapter.validate_python("2026-11-01T07:00:00+07:00")
        assert value.astimezone(UTC) == datetime(2026, 11, 1, tzinfo=UTC)

    @pytest.mark.parametrize("raw", ["not-a-date", "2026-13-01"])
    def test_invalid_value_fails_validation(self, raw):
        with pytest.raises(ValidationError):
            self.adapter.validate_python(raw)
