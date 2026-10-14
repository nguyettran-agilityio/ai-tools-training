"""Book schema shape / computed-field tests. No DB involved."""

import uuid
from datetime import UTC, datetime

from app.modules.book.schemas import BookRead, BookStatus


class TestBookReadStatus:
    def _make(self, available_copies: int) -> BookRead:
        return BookRead(
            id=uuid.uuid4(),
            title="Deep Work",
            author="Cal Newport",
            isbn="978-0-13-468599-1",
            description=None,
            category_id=uuid.uuid4(),
            total_copies=3,
            available_copies=available_copies,
            created_at=datetime.now(UTC),
        )

    def test_zero_available_copies_is_unavailable(self):
        book = self._make(available_copies=0)
        assert book.status == BookStatus.UNAVAILABLE

    def test_positive_available_copies_is_available(self):
        book = self._make(available_copies=2)
        assert book.status == BookStatus.AVAILABLE

    def test_status_appears_by_alias(self):
        book = self._make(available_copies=1)
        dumped = book.model_dump(by_alias=True)
        assert dumped["status"] == "available"
