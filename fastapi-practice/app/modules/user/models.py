"""User SQLModel table model."""

# Standard library
import uuid
from datetime import UTC, datetime

# Third-party
from sqlalchemy import Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

# Local application
# user
from app.modules.user.enums import UserRole

__all__ = ["User", "UserRole"]


class User(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    full_name: str
    role: UserRole = Field(
        default=UserRole.MEMBER,
        sa_column=Column(
            SAEnum(UserRole, values_callable=lambda e: [m.value for m in e]),
            nullable=False,
        ),
    )
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
