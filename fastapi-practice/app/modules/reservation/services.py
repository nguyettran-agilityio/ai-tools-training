# Standard library
import uuid
from datetime import UTC, datetime

# Local application
# core
from app.core.exceptions import AlreadyExistsError, ConflictError, ForbiddenError, NotFoundError
from app.core.mappers import pagination_offset, to_page
from app.core.notifications import BOOK_AVAILABLE, Notification, Notifier
from app.core.schemas import Page, PaginationParams
from app.core.service_utils import get_or_404

# book
from app.modules.book.repositories import BookRepositoryInterface

# reservation
from app.modules.reservation.enums import ReservationStatus
from app.modules.reservation.repositories import ReservationRepositoryInterface
from app.modules.reservation.schemas import ReservationCreate, ReservationRead

# user
from app.modules.user.repositories import UserRepositoryInterface


class ReservationService:
    def __init__(
        self,
        reservation_repository: ReservationRepositoryInterface,
        book_repository: BookRepositoryInterface,
        user_repository: UserRepositoryInterface,
        notifier: Notifier,
    ) -> None:
        self.reservation_repository = reservation_repository
        self.book_repository = book_repository
        # Only used to resolve a recipient's email for `EmailNotifier` — see
        # `notify_book_available` — same repository-interface dependency
        # shape as everything else here, not a new pattern.
        self.user_repository = user_repository
        self.notifier = notifier

    def create(self, user_id: uuid.UUID, data: ReservationCreate) -> ReservationRead:
        """Queue a reservation for a book; 409s if the caller already has an open one."""
        book = self.book_repository.get_by_id(data.book_id)
        if book is None:
            raise NotFoundError("Book not found")

        existing = self.reservation_repository.get_open_by_user_and_book(user_id, data.book_id)
        if existing is not None:
            raise AlreadyExistsError("You already have an active reservation for this book")

        return self.reservation_repository.create({"user_id": user_id, "book_id": data.book_id})

    def cancel(self, user_id: uuid.UUID, reservation_id: uuid.UUID) -> None:
        """Cancel the caller's own reservation; 409s if it's already fulfilled or cancelled."""
        reservation = get_or_404(
            self.reservation_repository, reservation_id, "Reservation not found"
        )

        if reservation.user_id != user_id:
            raise ForbiddenError("You can only cancel your own reservations")

        if reservation.status not in (
            ReservationStatus.PENDING,
            ReservationStatus.NOTIFIED,
        ):
            raise ConflictError("Reservation is already fulfilled or cancelled")

        self.reservation_repository.mark_cancelled(reservation_id)

    def my_reservations(
        self, user_id: uuid.UUID, pagination: PaginationParams
    ) -> Page[ReservationRead]:
        """Paginated listing of the caller's own reservations, newest first."""
        offset = pagination_offset(pagination.page, pagination.page_size)
        items, total = self.reservation_repository.list_by_user(
            user_id, offset, pagination.page_size
        )
        # No mapper_fn: the repository already returns `ReservationRead`.
        return to_page(items, total, pagination.page, pagination.page_size)

    async def notify_book_available(self, book_id: uuid.UUID) -> int:
        """Notify every user still waiting on `book_id` (FIFO order), marking each
        reservation `NOTIFIED`; returns how many were notified (0 if nobody's waiting)."""
        pending = self.reservation_repository.list_pending_for_book(book_id)

        for reservation in pending:
            user = self.user_repository.get_by_id(reservation.user_id)
            notification = Notification(
                user_id=reservation.user_id,
                type=BOOK_AVAILABLE,
                book_id=book_id,
                message="A book you reserved is now available.",
                email=user.email if user is not None else None,
            )
            await self.notifier.notify(notification)
            self.reservation_repository.mark_notified(reservation.id, datetime.now(UTC))

        return len(pending)
