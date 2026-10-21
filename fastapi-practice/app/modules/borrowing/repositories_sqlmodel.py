"""SQLModel-backed concrete `BorrowingRepositoryInterface` — the only file in
this module allowed to import `Borrowing` or `sqlmodel` itself.
"""

# Standard library
import uuid
from datetime import UTC, datetime

# Third-party
from sqlmodel import and_, func, select

# Local application
# core
from app.core.repository_sqlmodel import SQLModelBackend, apply_filters

# borrowing
from app.modules.borrowing.mappers import to_borrowing_read
from app.modules.borrowing.models import Borrowing
from app.modules.borrowing.repositories import BorrowingRepositoryInterface, BorrowingUpdateFields
from app.modules.borrowing.schemas import BorrowingRead


class BorrowingRepository(BorrowingRepositoryInterface):
    # Narrows the inherited `backend: CrudBackend[Any, ReadT, UpdateT]` to the
    # concrete SQLModel type for this file only, so mypy knows
    # `self.backend.session` exists here without leaking that knowledge
    # into the ORM-agnostic interface.
    backend: SQLModelBackend[Borrowing, BorrowingRead, BorrowingUpdateFields]

    def list_active_by_user(self, user_id: uuid.UUID) -> list[BorrowingRead]:
        items = self.backend.session.exec(
            select(Borrowing).where(Borrowing.user_id == user_id, Borrowing.returned_at.is_(None))
        ).all()
        return [to_borrowing_read(item) for item in items]

    def count_active_by_user(self, user_id: uuid.UUID) -> int:
        return self.backend.session.exec(
            select(func.count())
            .select_from(Borrowing)
            .where(Borrowing.user_id == user_id, Borrowing.returned_at.is_(None))
        ).one()

    def get_active_by_user_and_book(
        self, user_id: uuid.UUID, book_id: uuid.UUID
    ) -> BorrowingRead | None:
        borrowing = self.backend.session.exec(
            select(Borrowing).where(
                Borrowing.user_id == user_id,
                Borrowing.book_id == book_id,
                Borrowing.returned_at.is_(None),
            )
        ).first()
        return to_borrowing_read(borrowing) if borrowing is not None else None

    def list_by_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[BorrowingRead], int]:
        """Borrowing history for one user, newest first."""
        total = self.backend.session.exec(
            select(func.count()).select_from(Borrowing).where(Borrowing.user_id == user_id)
        ).one()
        items = self.backend.session.exec(
            select(Borrowing)
            .where(Borrowing.user_id == user_id)
            .order_by(Borrowing.borrowed_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [to_borrowing_read(item) for item in items], total

    def list_all(
        self,
        offset: int,
        limit: int,
        overdue_only: bool = False,
        now: datetime | None = None,
    ) -> tuple[list[BorrowingRead], int]:
        """All borrowings, optionally restricted to unreturned + past-due.
        `now` is a parameter so tests can pin "the current time"."""
        overdue_condition = None
        if overdue_only:
            reference_time = now if now is not None else datetime.now(UTC)
            overdue_condition = and_(
                Borrowing.returned_at.is_(None), Borrowing.due_date < reference_time
            )

        count_stmt, list_stmt = apply_filters(
            select(func.count()).select_from(Borrowing),
            select(Borrowing),
            [overdue_condition],
        )

        total = self.backend.session.exec(count_stmt).one()
        items = self.backend.session.exec(
            list_stmt.order_by(Borrowing.borrowed_at.desc()).offset(offset).limit(limit)
        ).all()
        return [to_borrowing_read(item) for item in items], total

    def count_active_by_book(self, book_id: uuid.UUID) -> int:
        return self.backend.session.exec(
            select(func.count())
            .select_from(Borrowing)
            .where(Borrowing.book_id == book_id, Borrowing.returned_at.is_(None))
        ).one()

    def mark_returned(self, id: uuid.UUID, returned_at: datetime) -> BorrowingRead:
        return self.backend.update(id, {"returned_at": returned_at})

    def mark_renewed(
        self, id: uuid.UUID, due_date: datetime, renewed_at: datetime
    ) -> BorrowingRead:
        return self.backend.update(id, {"due_date": due_date, "renewed_at": renewed_at})
