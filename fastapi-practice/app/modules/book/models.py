"""Book SQLModel table model. `available_copies` is the single source of
truth for lending state — there is no stored `status` column."""

# Standard library
import uuid
from datetime import UTC, datetime

# Third-party
from sqlmodel import Field, SQLModel


class Book(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(index=True)
    author: str
    isbn: str = Field(unique=True, index=True)
    description: str | None = None
    category_id: uuid.UUID = Field(foreign_key="category.id", index=True)
    total_copies: int
    available_copies: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
