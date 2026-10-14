"""Domain-level repository contract — zero ORM imports on purpose.

`CrudRepositoryInterface` forwards 5 generic CRUD methods to an injected
`CrudBackend` (one implementation per ORM, see `repository_sqlmodel.py`).
`UpdateT` is a per-module `TypedDict` (see each module's `repositories.py`)
so a typo'd or wrong-typed field in a partial update is a type error, not a
runtime surprise — `create()` still takes a plain dict since callers build
it from-scratch, but `update()`'s `changes` is always a sparse subset of a
known field set.
"""

# Standard library
import abc
import uuid
from collections.abc import Mapping
from typing import Any


class CrudBackend[ModelT, ReadT, UpdateT: Mapping[str, Any]](abc.ABC):
    """One implementation per ORM/store — never subclassed per module."""

    @abc.abstractmethod
    def get_by_id(self, id: uuid.UUID) -> ReadT | None: ...

    @abc.abstractmethod
    def list(self, offset: int, limit: int) -> tuple[list[ReadT], int]: ...

    @abc.abstractmethod
    def create(self, data: dict[str, Any]) -> ReadT: ...

    @abc.abstractmethod
    def update(self, id: uuid.UUID, changes: UpdateT) -> ReadT:
        """Assumes `id` already exists — callers check first (`get_or_404`)."""
        ...

    @abc.abstractmethod
    def delete(self, id: uuid.UUID) -> None:
        """A missing id is a no-op, not an error."""
        ...


class CrudRepositoryInterface[ReadT, UpdateT: Mapping[str, Any]](abc.ABC):  # noqa: B024
    """Every `<Module>RepositoryInterface` inherits this. Only `ReadT` (the DTO)
    and `UpdateT` (the update field set) are type parameters — the ORM model
    type is `backend`'s business, not this contract's."""

    def __init__(self, backend: CrudBackend[Any, ReadT, UpdateT]) -> None:
        # Composition, not inheritance: this class does NOT extend
        # CrudBackend — it holds one. That's what lets `deps.py` swap which
        # CrudBackend gets passed in without touching any module file.
        self.backend = backend

    def get_by_id(self, id: uuid.UUID) -> ReadT | None:
        return self.backend.get_by_id(id)

    def list(self, offset: int, limit: int) -> tuple[list[ReadT], int]:
        return self.backend.list(offset, limit)

    def create(self, data: dict[str, Any]) -> ReadT:
        return self.backend.create(data)

    def update(self, id: uuid.UUID, changes: UpdateT) -> ReadT:
        return self.backend.update(id, changes)

    def delete(self, id: uuid.UUID) -> None:
        return self.backend.delete(id)
