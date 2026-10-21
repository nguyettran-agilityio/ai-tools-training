# Standard library
import uuid
from datetime import UTC, datetime, timedelta

# Local application
# core
from app.core.exceptions import AlreadyExistsError, ConflictError, ForbiddenError, NotFoundError
from app.core.mappers import pagination_offset, to_page
from app.core.notifications import OVERDUE_REMINDER, Notification, Notifier
from app.core.schemas import Page, PaginationParams
from app.core.service_utils import get_or_404

# book
from app.modules.book.repositories import BookRepositoryInterface

# borrowing
from app.modules.borrowing.repositories import BorrowingRepositoryInterface
from app.modules.borrowing.schemas import (
    BorrowingRead,
    BorrowOutcome,
    BorrowRequest,
    BorrowResult,
)

# reservation
from app.modules.reservation.repositories import ReservationRepositoryInterface

# user
from app.modules.user.repositories import UserRepositoryInterface


def _now_utc() -> datetime:
    return datetime.now(UTC)


class BorrowingService:
    def __init__(
        self,
        borrowing_repository: BorrowingRepositoryInterface,
        book_repository: BookRepositoryInterface,
        reservation_repository: ReservationRepositoryInterface,
        user_repository: UserRepositoryInterface,
        borrow_limit: int,
        loan_duration_days: int,
        renewal_days: int,
        notifier: Notifier,
    ) -> None:
        self.borrowing_repository = borrowing_repository
        self.book_repository = book_repository
        # Repository, not `ReservationService` — a direct service-to-service
        # import would create a cross-module coupling (and a circular
        # import, since reservation notification is scheduled from the
        # router, not from here). Only the one query needed to close out the
        # caller's own reservation lives here; the FIFO "notify everyone
        # waiting" logic stays entirely in `ReservationService`.
        self.reservation_repository = reservation_repository
        # Only used to resolve a recipient's email for `EmailNotifier` — see
        # `notify_overdue` — same repository-interface dependency shape as
        # everything else here, not a new pattern.
        self.user_repository = user_repository
        self.borrow_limit = borrow_limit
        self.loan_duration_days = loan_duration_days
        self.renewal_days = renewal_days
        # `Notifier` interface, not a concrete notifier/service class — same
        # decoupling reasoning as `reservation_repository` above.
        self.notifier = notifier

    def borrow(self, user_id: uuid.UUID, data: BorrowRequest) -> BorrowResult:
        """Borrow a book if a copy is available (atomic claim, safe under
        race), else queue a reservation and return `BorrowOutcome.RESERVED`."""
        book = self.book_repository.get_by_id(data.book_id)
        if book is None:
            raise NotFoundError("Book not found")

        if self.borrowing_repository.count_active_by_user(user_id) >= self.borrow_limit:
            raise ConflictError(f"Borrow limit of {self.borrow_limit} books reached")

        if self.borrowing_repository.get_active_by_user_and_book(user_id, data.book_id) is not None:
            raise AlreadyExistsError("You already have this book borrowed")

        if not self.book_repository.try_decrement_available_copies(data.book_id):
            # No copy left to claim — queue a reservation instead.
            existing = self.reservation_repository.get_open_by_user_and_book(user_id, data.book_id)
            if existing is None:
                existing = self.reservation_repository.create(
                    {"user_id": user_id, "book_id": data.book_id}
                )
            return BorrowResult(kind=BorrowOutcome.RESERVED, reservation=existing)

        now = _now_utc()
        borrowing = self.borrowing_repository.create(
            {
                "user_id": user_id,
                "book_id": data.book_id,
                "borrowed_at": now,
                "due_date": now + timedelta(days=self.loan_duration_days),
                "returned_at": None,
            }
        )

        reservation = self.reservation_repository.get_open_by_user_and_book(user_id, data.book_id)
        if reservation is not None:
            self.reservation_repository.mark_fulfilled(reservation.id)

        return BorrowResult(kind=BorrowOutcome.BORROWED, borrowing=borrowing)

    def history(self, user_id: uuid.UUID, pagination: PaginationParams) -> Page[BorrowingRead]:
        """All of the caller's own borrowings (active, returned, overdue —
        `status` is computed per row), newest first."""
        offset = pagination_offset(pagination.page, pagination.page_size)
        items, total = self.borrowing_repository.list_by_user(user_id, offset, pagination.page_size)
        # No mapper_fn: the repository already returns `BorrowingRead`.
        return to_page(items, total, pagination.page, pagination.page_size)

    def current(self, user_id: uuid.UUID) -> list[BorrowingRead]:
        """Active-only borrowings for the caller. Not paginated — bounded
        above by `borrow_limit`, so a page would never be needed."""
        return self.borrowing_repository.list_active_by_user(user_id)

    def list_all(
        self, pagination: PaginationParams, overdue_only: bool = False
    ) -> Page[BorrowingRead]:
        """Admin view across every user's borrowings, optionally overdue-only."""
        now = _now_utc() if overdue_only else None
        offset = pagination_offset(pagination.page, pagination.page_size)
        items, total = self.borrowing_repository.list_all(
            offset, pagination.page_size, overdue_only, now
        )
        return to_page(items, total, pagination.page, pagination.page_size)

    def return_book(self, user_id: uuid.UUID, borrowing_id: uuid.UUID) -> BorrowingRead:
        """Mark a borrowing returned and give the copy back to the book's
        `available_copies`, capped at `total_copies` so it can never overshoot."""
        borrowing = get_or_404(self.borrowing_repository, borrowing_id, "Borrowing not found")

        if borrowing.user_id != user_id:
            raise ForbiddenError("You can only return your own borrowings")

        if borrowing.returned_at is not None:
            raise ConflictError("Book already returned")

        borrowing = self.borrowing_repository.mark_returned(borrowing_id, _now_utc())

        # Atomic UPDATE (capped at total_copies), not read-then-write — same
        # reasoning as the claim in `borrow()`.
        self.book_repository.increment_available_copies(borrowing.book_id)

        return borrowing

    def renew(self, user_id: uuid.UUID, borrowing_id: uuid.UUID) -> BorrowingRead:
        """Extend an active, not-yet-overdue loan by `renewal_days`, at most
        once per loan, and only while no other member is waiting on the book."""
        borrowing = get_or_404(self.borrowing_repository, borrowing_id, "Borrowing not found")

        if borrowing.user_id != user_id:
            raise ForbiddenError("You can only renew your own borrowings")

        if borrowing.returned_at is not None:
            raise ConflictError("Book already returned")

        if borrowing.renewed_at is not None:
            raise ConflictError("This loan has already been renewed")

        now = _now_utc()
        # Same overdue test as `BorrowingRead.status`.
        if borrowing.due_date < now:
            raise ConflictError("Overdue loans cannot be renewed")

        # The caller's own open reservation doesn't count — only someone
        # else waiting on the book blocks the renewal.
        if self.reservation_repository.count_open_by_book_excluding_user(
            borrowing.book_id, user_id
        ):
            raise ConflictError("This book has an open reservation")

        return self.borrowing_repository.mark_renewed(
            borrowing_id,
            due_date=borrowing.due_date + timedelta(days=self.renewal_days),
            renewed_at=now,
        )

    async def notify_overdue(self, now: datetime | None = None) -> int:
        """Admin-triggered sweep: notify every member holding an overdue book.
        Read + notify only; pulled in pages to bound memory."""
        reference_time = now or _now_utc()
        page_size = 100
        offset = 0
        sent = 0

        while True:
            items, total = self.borrowing_repository.list_all(
                offset, page_size, overdue_only=True, now=reference_time
            )
            for borrowing in items:
                book = self.book_repository.get_by_id(borrowing.book_id)
                book_label = book.title if book is not None else str(borrowing.book_id)
                user = self.user_repository.get_by_id(borrowing.user_id)
                notification = Notification(
                    user_id=borrowing.user_id,
                    type=OVERDUE_REMINDER,
                    book_id=borrowing.book_id,
                    message=f"Your borrowed book '{book_label}' is overdue — please return it.",
                    email=user.email if user is not None else None,
                )
                await self.notifier.notify(notification)
                sent += 1

            offset += page_size
            if offset >= total:
                break

        return sent
