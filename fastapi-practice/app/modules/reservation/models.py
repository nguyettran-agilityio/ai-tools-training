"""Reservation SQLModel table model."""

# Standard library
import uuid
from datetime import UTC, datetime

# Third-party
from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

# Local application
# reservation
from app.modules.reservation.enums import ReservationStatus

__all__ = ["Reservation", "ReservationStatus"]


class Reservation(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    book_id: uuid.UUID = Field(foreign_key="book.id", index=True)
    # Same fix as User.role (see the comment there): `values_callable`
    # makes SQLAlchemy's auto-derived Enum column persist by member VALUE
    # ("pending") instead of NAME ("PENDING").
    status: ReservationStatus = Field(
        default=ReservationStatus.PENDING,
        sa_column=Column(
            SAEnum(ReservationStatus, values_callable=lambda e: [m.value for m in e]),
            nullable=False,
        ),
    )
    # FIFO ordering key for the per-book reservation queue.
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notified_at: datetime | None = None
