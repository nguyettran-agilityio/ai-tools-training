# Standard library
import uuid
from datetime import UTC, datetime
from typing import cast

# Local application
# core
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    ConflictError,
    UnauthorizedError,
)
from app.core.mappers import pagination_offset, to_page
from app.core.schemas import Page, PaginationParams
from app.core.security import create_access_token, hash_password, verify_password
from app.core.service_utils import get_or_404
from app.core.token_denylist import InMemoryTokenDenylist

# borrowing
from app.modules.borrowing.repositories import BorrowingRepositoryInterface

# reservation
from app.modules.reservation.repositories import ReservationRepositoryInterface

# user
from app.modules.user.enums import UserRole
from app.modules.user.repositories import UserRepositoryInterface, UserUpdateFields
from app.modules.user.schemas import LoginRequest, UserCreate, UserRead, UserUpdate

# A real bcrypt hash of a password nobody will ever send, so that
# `verify_password()` still runs its full comparison on the "no such user"
# path — this keeps that path's timing close to the "wrong password" path
# and avoids leaking, via a timing side-channel, whether an email is registered.
_DUMMY_HASH = hash_password("no-such-user-dummy-password")


def _create_user(
    user_repository: UserRepositoryInterface, data: UserCreate, role: UserRole
) -> UserRead:
    """Shared by `AuthService.register` and `UserService.create` — one place
    for "email must be unique, hash the password"."""
    if user_repository.get_by_email(data.email) is not None:
        raise AlreadyExistsError("Email already registered")

    return user_repository.create(
        {
            "email": data.email,
            "hashed_password": hash_password(data.password),
            "full_name": data.full_name,
            "role": role,
            "is_active": True,
        }
    )


class AuthService:
    def __init__(
        self, user_repository: UserRepositoryInterface, denylist: InMemoryTokenDenylist
    ) -> None:
        self.user_repository = user_repository
        self.denylist = denylist

    def register(self, data: UserCreate) -> UserRead:
        """Self-service signup — always creates a `MEMBER`, never a caller-chosen role."""
        return _create_user(self.user_repository, data, UserRole.MEMBER)

    def login(self, data: LoginRequest) -> str:
        """Returns a signed access token, or raises `UnauthorizedError` with
        the same message for "no such user", "wrong password", and "inactive
        user" — never reveal which one it was."""
        credentials = self.user_repository.get_credentials_by_email(data.email)
        password_ok = verify_password(
            data.password, credentials.hashed_password if credentials else _DUMMY_HASH
        )

        if credentials is None or not password_ok or not credentials.is_active:
            raise UnauthorizedError("Invalid email or password")

        return create_access_token(subject=str(credentials.id))

    def logout(self, token_payload: dict) -> None:
        """Denylist the token's `jti` until it would have expired anyway."""
        jti = token_payload["jti"]
        expires_at = datetime.fromtimestamp(token_payload["exp"], tz=UTC)
        self.denylist.add(jti, expires_at)


class UserService:
    """Admin-only user management — separate from `AuthService` (self-service
    register/login/logout) on purpose; they serve different callers and
    different trust levels."""

    def __init__(
        self,
        user_repository: UserRepositoryInterface,
        borrowing_repository: BorrowingRepositoryInterface,
        reservation_repository: ReservationRepositoryInterface,
    ) -> None:
        self.user_repository = user_repository
        self.borrowing_repository = borrowing_repository
        self.reservation_repository = reservation_repository

    def list(
        self, role: UserRole | None, is_active: bool | None, pagination: PaginationParams
    ) -> Page[UserRead]:
        """Paginated user listing, optionally filtered by role and/or active status."""
        offset = pagination_offset(pagination.page, pagination.page_size)
        items, total = self.user_repository.list_filtered(
            offset, pagination.page_size, role, is_active
        )
        # No mapper_fn: the repository already returns `UserRead`.
        return to_page(items, total, pagination.page, pagination.page_size)

    def get(self, user_id: uuid.UUID) -> UserRead:
        """Fetch a single user by id, or raise `NotFoundError`."""
        return get_or_404(self.user_repository, user_id, "User not found")

    def create(self, data: UserCreate, role: UserRole = UserRole.MEMBER) -> UserRead:
        """Admin-created user with a caller-chosen role (unlike `AuthService.register`)."""
        return _create_user(self.user_repository, data, role)

    def update(self, user_id: uuid.UUID, data: UserUpdate, acting_user_id: uuid.UUID) -> UserRead:
        """Partial update; refuses to let an admin deactivate or demote their own account."""
        get_or_404(self.user_repository, user_id, "User not found")

        if user_id == acting_user_id and (data.is_active is False or data.role is UserRole.MEMBER):
            raise BadRequestError("You cannot deactivate or demote your own account")

        updates = cast(UserUpdateFields, data.model_dump(exclude_unset=True))
        return self.user_repository.update(user_id, updates)

    def delete(self, user_id: uuid.UUID, acting_user_id: uuid.UUID) -> None:
        """Delete a user; refuses self-deletion and 409s if they have active
        borrowings or open reservations."""
        get_or_404(self.user_repository, user_id, "User not found")

        if user_id == acting_user_id:
            raise BadRequestError("You cannot delete your own account")

        active_count = self.borrowing_repository.count_active_by_user(user_id)
        if active_count > 0:
            raise ConflictError(
                f"User has {active_count} active borrowing(s) and cannot be deleted"
            )

        reservation_count = self.reservation_repository.count_open_by_user(user_id)
        if reservation_count > 0:
            raise ConflictError(
                f"User has {reservation_count} open reservation(s) and cannot be deleted"
            )

        self.user_repository.delete(user_id)
