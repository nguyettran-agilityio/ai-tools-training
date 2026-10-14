"""User repository interface — zero ORM imports. Concrete implementation
lives in `repositories_sqlmodel.py`; services depend only on this interface.
"""

# Standard library
import abc
from typing import TypedDict

# Local application
# core
from app.core.repository_interface import CrudRepositoryInterface

# user
from app.modules.user.enums import UserRole
from app.modules.user.schemas import UserCredentials, UserRead


class UserUpdateFields(TypedDict, total=False):
    """Every field `update()` may be asked to change — mirrors `UserUpdate`
    exactly. `email`/`hashed_password` are deliberately absent: neither is
    updatable through this path (see `UserUpdate`)."""

    full_name: str
    is_active: bool
    role: UserRole


class UserRepositoryInterface(CrudRepositoryInterface[UserRead, UserUpdateFields]):
    @abc.abstractmethod
    def get_by_email(self, email: str) -> UserRead | None: ...

    @abc.abstractmethod
    def get_credentials_by_email(self, email: str) -> UserCredentials | None:
        """Auth-only lookup — the one path `hashed_password` leaves the
        repository through, via `UserCredentials` rather than `UserRead`."""
        ...

    @abc.abstractmethod
    def list_filtered(
        self, offset: int, limit: int, role: UserRole | None, is_active: bool | None
    ) -> tuple[list[UserRead], int]:
        """Admin listing with optional `role`/`is_active` filters."""
        ...
