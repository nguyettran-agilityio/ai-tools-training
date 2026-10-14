"""SQLAlchemy/SQLModel adapter for `CrudBackend`.

`SQLModelBackend` implements the generic CRUD contract once for every
SQLModel-backed module. `apply_filters` is a shared helper for custom
filtered-query methods (e.g. `search`, `list_filtered`).
"""

# Standard library
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, Self

# Third-party
from sqlmodel import Session, SQLModel, func, select

# Local application
from app.core.repository_interface import CrudBackend


class _SupportsWhere(Protocol):
    """Structural bound for `apply_filters` — any SQLAlchemy statement with
    a type-preserving `.where()` qualifies."""

    def where(self, *conditions: Any) -> Self: ...


class SQLModelBackend[ModelT: SQLModel, ReadT, UpdateT: Mapping[str, Any]](
    CrudBackend[ModelT, ReadT, UpdateT]
):
    """Generic CRUD for SQLModel/SQLAlchemy. `model`/`to_dto` are
    constructor arguments, built once per request by `core/deps.py`."""

    def __init__(
        self, session: Session, model: type[ModelT], to_dto: Callable[[ModelT], ReadT]
    ) -> None:
        self.session = session
        self.model = model
        self.to_dto = to_dto

    def get_by_id(self, id: uuid.UUID) -> ReadT | None:
        entity = self.session.get(self.model, id)
        return self.to_dto(entity) if entity is not None else None

    def list(self, offset: int, limit: int) -> tuple[list[ReadT], int]:
        total = self.session.exec(select(func.count()).select_from(self.model)).one()
        items = self.session.exec(select(self.model).offset(offset).limit(limit)).all()
        return [self.to_dto(item) for item in items], total

    def create(self, data: dict[str, Any]) -> ReadT:
        entity = self.model(**data)
        self.session.add(entity)
        self.session.flush()
        self.session.refresh(entity)
        return self.to_dto(entity)

    def update(self, id: uuid.UUID, changes: UpdateT) -> ReadT:
        entity = self.session.get(self.model, id)
        if entity is None:
            # A caller-contract violation, not a normal "not found" request —
            # callers must check existence first (see `get_or_404`). Raised
            # instead of asserted so this still fails loudly under `python -O`.
            raise LookupError(f"update() requires an existing row (id={id})")
        for field, value in changes.items():
            setattr(entity, field, value)
        self.session.add(entity)
        self.session.flush()
        self.session.refresh(entity)
        return self.to_dto(entity)

    def delete(self, id: uuid.UUID) -> None:
        entity = self.session.get(self.model, id)
        if entity is not None:
            self.session.delete(entity)
            self.session.flush()


def apply_filters[CountStmtT: _SupportsWhere, ListStmtT: _SupportsWhere](
    count_stmt: CountStmtT, list_stmt: ListStmtT, conditions: Sequence[Any | None]
) -> tuple[CountStmtT, ListStmtT]:
    """Apply the same optional WHERE conditions to a count and a list statement
    in lockstep. A `None` entry in `conditions` means "no filter" and is skipped.

    Usage: `apply_filters(count_stmt, list_stmt, [User.role == role if role else None])`
    """
    for condition in conditions:
        if condition is not None:
            count_stmt = count_stmt.where(condition)
            list_stmt = list_stmt.where(condition)
    return count_stmt, list_stmt
