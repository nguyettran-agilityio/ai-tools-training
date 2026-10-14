"""Book Pydantic DTOs (request/response schemas). `status` is a `@computed_field`
derived from `available_copies`, never a stored field.
"""

# Standard library
import uuid
from datetime import datetime
from enum import StrEnum

# Third-party
from pydantic import Field, computed_field

# Local application
# core
from app.core.schemas import CamelModel


class BookStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class BookCreate(CamelModel):
    title: str
    author: str
    isbn: str
    description: str | None = None
    category_id: uuid.UUID
    total_copies: int = Field(ge=0)
    # available_copies is deliberately not accepted from the client — it
    # starts equal to total_copies, decided by the service layer.


class BookUpdate(CamelModel):
    title: str | None = None
    author: str | None = None
    isbn: str | None = None
    description: str | None = None
    category_id: uuid.UUID | None = None
    total_copies: int | None = Field(default=None, ge=0)


class BookRead(CamelModel):
    id: uuid.UUID
    title: str
    author: str
    isbn: str
    description: str | None
    category_id: uuid.UUID
    total_copies: int
    available_copies: int
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> BookStatus:
        return BookStatus.AVAILABLE if self.available_copies > 0 else BookStatus.UNAVAILABLE
