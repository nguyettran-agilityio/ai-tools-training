"""SQLModel-backed concrete `BorrowingRepositoryInterface` and
`BorrowingBanRepositoryInterface` — the only file in this module allowed to
import `Borrowing`, `BorrowingBan` or `sqlmodel` itself.
"""

# Standard library
import uuid
from datetime import UTC, datetime

# Third-party
from sqlalchemy import case
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import and_, col, func, select

# Local application
# core
from app.core.repository_sqlmodel import SQLModelBackend, apply_filters

# borrowing
from app.modules.borrowing.mappers import to_borrowing_ban_read, to_borrowing_read
from app.modules.borrowing.models import Borrowing, BorrowingBan
from app.modules.borrowing.repositories import (
    BorrowingBanRepositoryInterface,
    BorrowingBanUpdateFields,
    BorrowingRepositoryInterface,
    BorrowingUpdateFields,
)
from app.modules.borrowing.schemas import BorrowingBanRead, BorrowingRead


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

    def list_late_returns(
        self,
        offset: int,
        limit: int,
        returned_from: datetime | None = None,
        returned_to: datetime | None = None,
    ) -> tuple[list[BorrowingRead], int]:
        """SQLite stores naive datetimes and ignores any offset when
        comparing, so callers must pass bounds already converted to UTC."""
        # `col()`: `returned_at` is typed `datetime | None`, which mypy won't
        # compare; at runtime it is the same column expression.
        returned_at = col(Borrowing.returned_at)
        count_stmt, list_stmt = apply_filters(
            select(func.count()).select_from(Borrowing),
            select(Borrowing),
            [
                returned_at.is_not(None),
                returned_at > Borrowing.due_date,
                returned_at >= returned_from if returned_from is not None else None,
                returned_at <= returned_to if returned_to is not None else None,
            ],
        )

        total = self.backend.session.exec(count_stmt).one()
        items = self.backend.session.exec(
            list_stmt.order_by(returned_at.desc()).offset(offset).limit(limit)
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


class BorrowingBanRepository(BorrowingBanRepositoryInterface):
    backend: SQLModelBackend[BorrowingBan, BorrowingBanRead, BorrowingBanUpdateFields]

    def get_active_by_user(self, user_id: uuid.UUID, now: datetime) -> BorrowingBanRead | None:
        ban = self.backend.session.exec(
            select(BorrowingBan).where(
                BorrowingBan.user_id == user_id, BorrowingBan.banned_until > now
            )
        ).first()
        return to_borrowing_ban_read(ban) if ban is not None else None

    def extend(
        self,
        user_id: uuid.UUID,
        banned_until: datetime,
        source_borrowing_id: uuid.UUID,
        now: datetime,
    ) -> BorrowingBanRead:
        """One `INSERT ... ON CONFLICT DO UPDATE`, not read-then-write, so two
        concurrent late returns cannot lose the later date. SQLite-specific
        (scalar `MAX(a, b)`); revisit if the DB changes. Inside `SET`, the
        bare column refers to the row's old value, so every `CASE` below
        compares against the old `banned_until`, whatever the column order."""
        stmt = sqlite_insert(BorrowingBan).values(
            user_id=user_id,
            banned_until=banned_until,
            source_borrowing_id=source_borrowing_id,
            created_at=now,
            updated_at=now,
        )
        moves_later = stmt.excluded.banned_until > BorrowingBan.banned_until
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            # `created_at` is left out on purpose: it keeps the first insert.
            set_={
                "banned_until": func.max(BorrowingBan.banned_until, stmt.excluded.banned_until),
                "source_borrowing_id": case(
                    (moves_later, stmt.excluded.source_borrowing_id),
                    else_=BorrowingBan.source_borrowing_id,
                ),
                "updated_at": case(
                    (moves_later, stmt.excluded.updated_at), else_=BorrowingBan.updated_at
                ),
            },
        )
        self.backend.session.exec(stmt)
        self.backend.session.flush()
        # `populate_existing`: the identity map may still hold the pre-upsert
        # row from an earlier read in this session.
        ban = self.backend.session.exec(
            select(BorrowingBan)
            .where(BorrowingBan.user_id == user_id)
            .execution_options(populate_existing=True)
        ).one()
        return to_borrowing_ban_read(ban)

    def list_active(
        self, offset: int, limit: int, now: datetime
    ) -> tuple[list[BorrowingBanRead], int]:
        count_stmt, list_stmt = apply_filters(
            select(func.count()).select_from(BorrowingBan),
            select(BorrowingBan),
            [BorrowingBan.banned_until > now],
        )
        total = self.backend.session.exec(count_stmt).one()
        items = self.backend.session.exec(
            list_stmt.order_by(BorrowingBan.banned_until.asc()).offset(offset).limit(limit)
        ).all()
        return [to_borrowing_ban_read(item) for item in items], total
