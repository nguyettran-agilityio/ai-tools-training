"""Shared schema base classes used across every domain module's `schemas.py`.

`CamelModel`: Python/DB stays snake_case, JSON stays camelCase.
"""

# Third-party
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class PaginationParams(CamelModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)


class Page[T](CamelModel):
    """Generic paginated response wrapper; `total_pages` is computed by the
    service/mapper layer, not this schema."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
