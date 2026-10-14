"""Category Pydantic DTOs (request/response schemas)."""

# Standard library
import uuid
from datetime import datetime

# Third-party
from pydantic import Field, field_validator

# Local application
# core
from app.core.schemas import CamelModel


class CategoryCreate(CamelModel):
    name: str = Field(min_length=1)
    description: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        # mode="before" so `min_length` (core validation) is checked
        # against the already-stripped value — a whitespace-only name
        # like "   " must fail, not slip through as length-1.
        return v.strip() if isinstance(v, str) else v


class CategoryUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        # Same rule as CategoryCreate — but `name` is optional here, so a
        # caller not touching the name at all (None) must pass through
        # untouched rather than being coerced into a stripped empty string.
        return v.strip() if isinstance(v, str) else v


class CategoryRead(CamelModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
