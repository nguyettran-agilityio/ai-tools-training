# Standard library
import uuid

# Third-party
from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

# Local application
# core
from app.core.deps import (
    get_borrowing_service,
    get_current_user,
    get_reservation_service,
    require_admin,
)
from app.core.schemas import Page, PaginationParams

# borrowing
from app.modules.borrowing.schemas import (
    BorrowingRead,
    BorrowOutcome,
    BorrowRequest,
    OverdueNotifyResult,
)
from app.modules.borrowing.services import BorrowingService

# reservation
from app.modules.reservation.services import ReservationService

# user
from app.modules.user.schemas import UserRead

router = APIRouter(prefix="/borrowings", tags=["borrowings"])


# ── Static routes (must precede /{borrowing_id}) ────────────────────────────


@router.get("/history", response_model=Page[BorrowingRead])
def history(
    pagination: PaginationParams = Depends(PaginationParams),
    current_user: UserRead = Depends(get_current_user),
    service: BorrowingService = Depends(get_borrowing_service),
) -> Page[BorrowingRead]:
    return service.history(current_user.id, pagination)


@router.get("/current", response_model=list[BorrowingRead])
def current(
    current_user: UserRead = Depends(get_current_user),
    service: BorrowingService = Depends(get_borrowing_service),
) -> list[BorrowingRead]:
    return service.current(current_user.id)


@router.get("/overdue", response_model=Page[BorrowingRead])
def overdue(
    pagination: PaginationParams = Depends(PaginationParams),
    _current_user: UserRead = Depends(require_admin),
    service: BorrowingService = Depends(get_borrowing_service),
) -> Page[BorrowingRead]:
    return service.list_all(pagination, overdue_only=True)


@router.get("", response_model=Page[BorrowingRead])
def list_all(
    overdue_only: bool = Query(default=False, alias="overdueOnly"),
    pagination: PaginationParams = Depends(PaginationParams),
    _current_user: UserRead = Depends(require_admin),
    service: BorrowingService = Depends(get_borrowing_service),
) -> Page[BorrowingRead]:
    return service.list_all(pagination, overdue_only=overdue_only)


@router.post("/notify-overdue", response_model=OverdueNotifyResult)
async def notify_overdue(
    _current_user: UserRead = Depends(require_admin),
    service: BorrowingService = Depends(get_borrowing_service),
) -> OverdueNotifyResult:
    """Admin-triggered sweep — no scheduler involved. Sends every overdue
    holder an `OVERDUE_REMINDER` through the same pipeline as `BOOK_AVAILABLE`."""
    reminders_sent = await service.notify_overdue()
    return OverdueNotifyResult(reminders_sent=reminders_sent)


# ── Path-param routes ────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED, response_model=None)
def borrow(
    data: BorrowRequest,
    current_user: UserRead = Depends(get_current_user),
    service: BorrowingService = Depends(get_borrowing_service),
) -> BorrowingRead | JSONResponse:
    result = service.borrow(current_user.id, data)

    if result.kind == BorrowOutcome.RESERVED:
        # Race-condition safety net: the book went out of stock between the
        # caller's UI showing it as available and this request. 202, not
        # 201 — nothing was borrowed; the caller was queued instead. The
        # decorator's `status_code=201` only applies when the function
        # returns normally, so this has to go out as an explicit
        # `JSONResponse` to get a different status code.
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=jsonable_encoder(result.reservation),
        )

    assert result.borrowing is not None
    return result.borrowing


@router.post("/{borrowing_id}/return", response_model=BorrowingRead)
def return_book(
    borrowing_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: UserRead = Depends(get_current_user),
    service: BorrowingService = Depends(get_borrowing_service),
    reservation_service: ReservationService = Depends(get_reservation_service),
) -> BorrowingRead:
    borrowing = service.return_book(current_user.id, borrowing_id)
    # Always schedule — `notify_book_available` is a no-op (returns 0) when
    # nobody is waiting on this book, so there's no need to check
    # availability/reservation state here first.
    background_tasks.add_task(reservation_service.notify_book_available, borrowing.book_id)

    return borrowing
