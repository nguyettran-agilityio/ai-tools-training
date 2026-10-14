"""Generic mapping helpers shared across every module's `mappers.py`.

No `fastapi` imports here — mappers are pure functions, model in, schema
out; used by services (a later epic), not routers directly.
"""

# Standard library
import math
from collections.abc import Callable
from typing import cast

# Local application
# core
from app.core.schemas import Page


def pagination_offset(page: int, page_size: int) -> int:
    """Zero-based row offset for `page` (1-based) at `page_size` rows per page."""
    return (page - 1) * page_size


def to_page[ModelT, ReadT](
    items: list[ModelT],
    total: int,
    page: int,
    page_size: int,
    mapper_fn: Callable[[ModelT], ReadT] | None = None,
) -> Page[ReadT]:
    """Map one page of models to a `Page` of read schemas.

    `total_pages = ceil(total / page_size)`, 0 for an empty result set.
    `mapper_fn` defaults to identity (repository already returns DTOs);
    pass a module's `to_x_read` when the repository returns raw models.
    """
    total_pages = math.ceil(total / page_size) if total else 0
    effective_mapper = (
        mapper_fn if mapper_fn is not None else cast("Callable[[ModelT], ReadT]", lambda item: item)
    )
    return Page[ReadT](
        items=[effective_mapper(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
