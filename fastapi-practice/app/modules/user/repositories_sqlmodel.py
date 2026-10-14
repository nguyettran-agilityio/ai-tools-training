"""SQLModel-backed concrete `UserRepositoryInterface` — the only file in this
module allowed to import `User` or `sqlmodel` itself.
"""

# Third-party
from sqlmodel import func, select

# Local application
# core
from app.core.repository_sqlmodel import SQLModelBackend, apply_filters

# user
from app.modules.user.mappers import to_user_credentials, to_user_read
from app.modules.user.models import User, UserRole
from app.modules.user.repositories import UserRepositoryInterface, UserUpdateFields
from app.modules.user.schemas import UserCredentials, UserRead


class UserRepository(UserRepositoryInterface):
    # Narrows the inherited `backend: CrudBackend[Any, ReadT, UpdateT]` to the
    # concrete SQLModel type for this file only, so mypy knows
    # `self.backend.session` exists here without leaking that knowledge
    # into the ORM-agnostic interface.
    backend: SQLModelBackend[User, UserRead, UserUpdateFields]

    def get_by_email(self, email: str) -> UserRead | None:
        user = self.backend.session.exec(select(User).where(User.email == email)).first()
        return to_user_read(user) if user is not None else None

    def get_credentials_by_email(self, email: str) -> UserCredentials | None:
        user = self.backend.session.exec(select(User).where(User.email == email)).first()
        return to_user_credentials(user) if user is not None else None

    def list_filtered(
        self, offset: int, limit: int, role: UserRole | None, is_active: bool | None
    ) -> tuple[list[UserRead], int]:
        count_stmt, list_stmt = apply_filters(
            select(func.count()).select_from(User),
            select(User),
            [
                User.role == role if role is not None else None,
                User.is_active == is_active if is_active is not None else None,
            ],
        )
        total = self.backend.session.exec(count_stmt).one()
        items = self.backend.session.exec(list_stmt.offset(offset).limit(limit)).all()
        return [to_user_read(item) for item in items], total
