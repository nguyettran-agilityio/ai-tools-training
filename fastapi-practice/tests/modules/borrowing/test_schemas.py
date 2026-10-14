"""Borrowing schema computed-field tests. No DB involved."""

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.borrowing.schemas import BorrowingRead, BorrowingStatus


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
