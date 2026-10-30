# Standard library
import uuid

# Third-party
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

# Local application
# core
from app.core.config import get_settings
from app.core.db import get_session
from app.core.exceptions import ForbiddenError, TooManyRequestsError, UnauthorizedError
from app.core.notifications import get_notifier
from app.core.rate_limiter import get_rate_limiter
from app.core.repository_sqlmodel import SQLModelBackend
from app.core.security import decode_access_token
from app.core.token_denylist import InMemoryTokenDenylist, get_token_denylist

# book
from app.modules.book.mappers import to_book_read
from app.modules.book.models import Book
from app.modules.book.repositories import BookRepositoryInterface, BookUpdateFields
from app.modules.book.repositories_sqlmodel import BookRepository
from app.modules.book.schemas import BookRead
from app.modules.book.services import BookService

# borrowing
from app.modules.borrowing.mappers import to_borrowing_ban_read, to_borrowing_read
from app.modules.borrowing.models import Borrowing, BorrowingBan
from app.modules.borrowing.repositories import (
    BorrowingBanRepositoryInterface,
    BorrowingBanUpdateFields,
    BorrowingRepositoryInterface,
    BorrowingUpdateFields,
)
from app.modules.borrowing.repositories_sqlmodel import BorrowingBanRepository, BorrowingRepository
from app.modules.borrowing.schemas import BorrowingBanRead, BorrowingRead
from app.modules.borrowing.services import BorrowingService

# category
from app.modules.category.mappers import to_category_read
from app.modules.category.models import Category
from app.modules.category.repositories import CategoryRepositoryInterface, CategoryUpdateFields
from app.modules.category.repositories_sqlmodel import CategoryRepository
from app.modules.category.schemas import CategoryRead
from app.modules.category.services import CategoryService

# reservation
from app.modules.reservation.mappers import to_reservation_read
from app.modules.reservation.models import Reservation
from app.modules.reservation.repositories import (
    ReservationRepositoryInterface,
    ReservationUpdateFields,
)
from app.modules.reservation.repositories_sqlmodel import ReservationRepository
from app.modules.reservation.schemas import ReservationRead
from app.modules.reservation.services import ReservationService

# user
from app.modules.user.mappers import to_user_read
from app.modules.user.models import User, UserRole
from app.modules.user.repositories import UserRepositoryInterface, UserUpdateFields
from app.modules.user.repositories_sqlmodel import UserRepository
from app.modules.user.schemas import UserRead
from app.modules.user.services import AuthService, UserService

# `auto_error=False` so a missing header is handled by us — `UnauthorizedError`,
# and thus the shared `ErrorResponse` envelope — instead of HTTPBearer's
# built-in `HTTPException(403, "Not authenticated")`.
bearer_scheme = HTTPBearer(auto_error=False)


# ── Repository / service providers ──────────────────────────────────────────


def get_user_repository(
    session: Session = Depends(get_session),
) -> UserRepositoryInterface:
    # This is the one place allowed to know the concrete implementation
    # (`UserRepository`) — every caller downstream (services, other
    # providers) only ever sees `UserRepositoryInterface`.
    backend = SQLModelBackend[User, UserRead, UserUpdateFields](session, User, to_user_read)
    return UserRepository(backend)


def get_auth_service(
    user_repository: UserRepositoryInterface = Depends(get_user_repository),
    denylist: InMemoryTokenDenylist = Depends(get_token_denylist),
) -> AuthService:
    return AuthService(user_repository, denylist)


def get_category_repository(
    session: Session = Depends(get_session),
) -> CategoryRepositoryInterface:
    backend = SQLModelBackend[Category, CategoryRead, CategoryUpdateFields](
        session, Category, to_category_read
    )
    return CategoryRepository(backend)


def get_book_repository(
    session: Session = Depends(get_session),
) -> BookRepositoryInterface:
    backend = SQLModelBackend[Book, BookRead, BookUpdateFields](session, Book, to_book_read)
    return BookRepository(backend)


def get_category_service(
    category_repository: CategoryRepositoryInterface = Depends(get_category_repository),
    book_repository: BookRepositoryInterface = Depends(get_book_repository),
) -> CategoryService:
    return CategoryService(category_repository, book_repository)


def get_borrowing_repository(
    session: Session = Depends(get_session),
) -> BorrowingRepositoryInterface:
    backend = SQLModelBackend[Borrowing, BorrowingRead, BorrowingUpdateFields](
        session, Borrowing, to_borrowing_read
    )
    return BorrowingRepository(backend)


def get_borrowing_ban_repository(
    session: Session = Depends(get_session),
) -> BorrowingBanRepositoryInterface:
    backend = SQLModelBackend[BorrowingBan, BorrowingBanRead, BorrowingBanUpdateFields](
        session, BorrowingBan, to_borrowing_ban_read
    )
    return BorrowingBanRepository(backend)


def get_reservation_repository(
    session: Session = Depends(get_session),
) -> ReservationRepositoryInterface:
    backend = SQLModelBackend[Reservation, ReservationRead, ReservationUpdateFields](
        session, Reservation, to_reservation_read
    )
    return ReservationRepository(backend)


def get_reservation_service(
    reservation_repository: ReservationRepositoryInterface = Depends(get_reservation_repository),
    book_repository: BookRepositoryInterface = Depends(get_book_repository),
    user_repository: UserRepositoryInterface = Depends(get_user_repository),
) -> ReservationService:
    return ReservationService(
        reservation_repository, book_repository, user_repository, get_notifier()
    )


def get_borrowing_service(
    borrowing_repository: BorrowingRepositoryInterface = Depends(get_borrowing_repository),
    book_repository: BookRepositoryInterface = Depends(get_book_repository),
    reservation_repository: ReservationRepositoryInterface = Depends(get_reservation_repository),
    user_repository: UserRepositoryInterface = Depends(get_user_repository),
    borrowing_ban_repository: BorrowingBanRepositoryInterface = Depends(
        get_borrowing_ban_repository
    ),
) -> BorrowingService:
    settings = get_settings()
    return BorrowingService(
        borrowing_repository,
        book_repository,
        reservation_repository,
        user_repository,
        settings.borrow_limit,
        settings.loan_duration_days,
        settings.renewal_days,
        get_notifier(),
        borrowing_ban_repository,
        settings.late_return_ban_days,
    )


def get_book_service(
    book_repository: BookRepositoryInterface = Depends(get_book_repository),
    category_repository: CategoryRepositoryInterface = Depends(get_category_repository),
    borrowing_repository: BorrowingRepositoryInterface = Depends(get_borrowing_repository),
    reservation_repository: ReservationRepositoryInterface = Depends(get_reservation_repository),
) -> BookService:
    return BookService(
        book_repository, category_repository, borrowing_repository, reservation_repository
    )


def get_user_service(
    user_repository: UserRepositoryInterface = Depends(get_user_repository),
    borrowing_repository: BorrowingRepositoryInterface = Depends(get_borrowing_repository),
    reservation_repository: ReservationRepositoryInterface = Depends(get_reservation_repository),
) -> UserService:
    return UserService(user_repository, borrowing_repository, reservation_repository)


# ── Auth dependencies ────────────────────────────────────────────────────────


def get_bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise UnauthorizedError("Not authenticated")
    return credentials.credentials


def _resolve_user(
    token: str, user_repository: UserRepositoryInterface, denylist: InMemoryTokenDenylist
) -> UserRead:
    payload = decode_access_token(token)

    if denylist.is_denied(payload["jti"]):
        raise UnauthorizedError("Token has been revoked")

    user = user_repository.get_by_id(uuid.UUID(payload["sub"]))
    if user is None:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise UnauthorizedError("Inactive user")

    return user


def get_current_user(
    token: str = Depends(get_bearer_token),
    user_repository: UserRepositoryInterface = Depends(get_user_repository),
    denylist: InMemoryTokenDenylist = Depends(get_token_denylist),
) -> UserRead:
    return _resolve_user(token, user_repository, denylist)


def require_admin(user: UserRead = Depends(get_current_user)) -> UserRead:
    if user.role != UserRole.ADMIN:
        raise ForbiddenError("Admin privileges required")
    return user


def rate_limit_auth(request: Request) -> None:
    """Guards `/auth/login` and `/auth/register` against brute-force/spam,
    keyed by client IP. See `core/rate_limiter.py`."""
    key = request.client.host if request.client else "unknown"
    if not get_rate_limiter().is_allowed(key):
        raise TooManyRequestsError()
