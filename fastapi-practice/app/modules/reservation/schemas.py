"""Reservation Pydantic DTOs (request/response schemas)."""

# Standard library
import uuid
from datetime import datetime

# Local application
# core
from app.core.schemas import CamelModel

# reservation
from app.modules.reservation.enums import ReservationStatus


class ReservationCreate(CamelModel):
    book_id: uuid.UUID


class ReservationRead(CamelModel):
    id: uuid.UUID
    user_id: uuid.UUID
    book_id: uuid.UUID
    status: ReservationStatus
    created_at: datetime
    notified_at: datetime | None
