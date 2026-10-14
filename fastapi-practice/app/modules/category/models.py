"""Category SQLModel table model."""

# Standard library
import uuid
from datetime import UTC, datetime

# Third-party
from sqlmodel import Field, SQLModel


class Category(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
