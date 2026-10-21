"""SQLModel-backed concrete `ReservationRepositoryInterface` — the only file
in this module allowed to import `Reservation` or `sqlmodel` itself.
"""

# Standard library
import uuid
from datetime import datetime

# Third-party
from sqlmodel import func, select

# Local application
# core
from app.core.repository_sqlmodel import SQLModelBackend

# reservation
from app.modules.reservation.mappers import to_reservation_read
from app.modules.reservation.models import Reservation, ReservationStatus
from app.modules.reservation.repositories import (
    ReservationRepositoryInterface,
    ReservationUpdateFields,
)
from app.modules.reservation.schemas import ReservationRead


class ReservationRepository(ReservationRepositoryInterface):
    # Narrows the inherited `backend: CrudBackend[Any, ReadT, UpdateT]` to the
    # concrete SQLModel type for this file only, so mypy knows
    # `self.backend.session` exists here without leaking that knowledge
    # into the ORM-agnostic interface.
    backend: SQLModelBackend[Reservation, ReservationRead, ReservationUpdateFields]

    def list_pending_for_book(self, book_id: uuid.UUID) -> list[ReservationRead]:
        items = self.backend.session.exec(
            select(Reservation)
            .where(
                Reservation.book_id == book_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.NOTIFIED]),
            )
            .order_by(Reservation.created_at.asc())
        ).all()
        return [to_reservation_read(item) for item in items]

    def get_open_by_user_and_book(
        self, user_id: uuid.UUID, book_id: uuid.UUID
    ) -> ReservationRead | None:
        reservation = self.backend.session.exec(
            select(Reservation).where(
                Reservation.user_id == user_id,
                Reservation.book_id == book_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.NOTIFIED]),
            )
        ).first()
        return to_reservation_read(reservation) if reservation is not None else None

    def list_by_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[ReservationRead], int]:
        total = self.backend.session.exec(
            select(func.count()).select_from(Reservation).where(Reservation.user_id == user_id)
        ).one()
        items = self.backend.session.exec(
            select(Reservation)
            .where(Reservation.user_id == user_id)
            .order_by(Reservation.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [to_reservation_read(item) for item in items], total

    def count_open_by_book(self, book_id: uuid.UUID) -> int:
        return self.backend.session.exec(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.book_id == book_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.NOTIFIED]),
            )
        ).one()

    def count_open_by_book_excluding_user(self, book_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return self.backend.session.exec(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.book_id == book_id,
                Reservation.user_id != user_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.NOTIFIED]),
            )
        ).one()

    def count_open_by_user(self, user_id: uuid.UUID) -> int:
        return self.backend.session.exec(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.user_id == user_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.NOTIFIED]),
            )
        ).one()

    def mark_cancelled(self, id: uuid.UUID) -> ReservationRead:
        return self.backend.update(id, {"status": ReservationStatus.CANCELLED})

    def mark_notified(self, id: uuid.UUID, notified_at: datetime) -> ReservationRead:
        return self.backend.update(
            id, {"status": ReservationStatus.NOTIFIED, "notified_at": notified_at}
        )

    def mark_fulfilled(self, id: uuid.UUID) -> ReservationRead:
        return self.backend.update(id, {"status": ReservationStatus.FULFILLED})
