"""Reservation mappers: model -> read schema. No Create/Update-to-model logic here —
that's the service layer's job (a later epic)."""

# Local application
# reservation
from app.modules.reservation.models import Reservation
from app.modules.reservation.schemas import ReservationRead


def to_reservation_read(reservation: Reservation) -> ReservationRead:
    return ReservationRead.model_validate(reservation)
