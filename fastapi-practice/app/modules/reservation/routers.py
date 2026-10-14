# Standard library
import uuid

# Third-party
from fastapi import APIRouter, Depends, Response, status

# Local application
# core
from app.core.deps import get_current_user, get_reservation_service
from app.core.schemas import Page, PaginationParams

# reservation
from app.modules.reservation.schemas import ReservationCreate, ReservationRead
from app.modules.reservation.services import ReservationService

# user
from app.modules.user.schemas import UserRead

router = APIRouter(prefix="/reservations", tags=["reservations"])


# ── Static routes (must precede /{reservation_id}) ──────────────────────────


@router.get("/my", response_model=Page[ReservationRead])
def my_reservations(
    pagination: PaginationParams = Depends(PaginationParams),
    current_user: UserRead = Depends(get_current_user),
    service: ReservationService = Depends(get_reservation_service),
) -> Page[ReservationRead]:
    return service.my_reservations(current_user.id, pagination)


# ── Path-param routes ────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ReservationRead)
def create(
    data: ReservationCreate,
    current_user: UserRead = Depends(get_current_user),
    service: ReservationService = Depends(get_reservation_service),
) -> ReservationRead:
    return service.create(current_user.id, data)


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel(
    reservation_id: uuid.UUID,
    current_user: UserRead = Depends(get_current_user),
    service: ReservationService = Depends(get_reservation_service),
) -> Response:
    service.cancel(current_user.id, reservation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
