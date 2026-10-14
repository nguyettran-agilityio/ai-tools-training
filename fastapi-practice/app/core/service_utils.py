"""Small helpers shared across every module's `services.py` — service-layer
concerns like turning a repository's `None` into a domain exception."""

# Standard library
import uuid
from typing import Any

# Local application
# core
from app.core.exceptions import NotFoundError
from app.core.repository_interface import CrudRepositoryInterface


def get_or_404[ModelT](
    repository: CrudRepositoryInterface[ModelT, Any], id: uuid.UUID, message: str
) -> ModelT:
    """Fetch `id` from `repository`, or raise `NotFoundError(message)`."""
    entity = repository.get_by_id(id)
    if entity is None:
        raise NotFoundError(message)
    return entity
