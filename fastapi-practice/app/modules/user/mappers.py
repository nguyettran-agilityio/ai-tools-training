"""User mappers: model -> read schema. No Create/Update-to-model logic here —
that's the service layer's job (a later epic)."""

# Local application
# user
from app.modules.user.models import User
from app.modules.user.schemas import UserCredentials, UserRead


def to_user_read(user: User) -> UserRead:
    return UserRead.model_validate(user)


def to_user_credentials(user: User) -> UserCredentials:
    return UserCredentials.model_validate(user)
