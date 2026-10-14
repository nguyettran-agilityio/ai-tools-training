"""Tests for the generic repository pattern itself (app/core/repository_interface.py
+ repository_sqlmodel.py), against an in-memory SQLite DB.

Exercised through `CategoryRepository` — it adds nothing beyond the
inherited CRUD (which forwards to `backend`), so it's a clean proxy for
`SQLModelBackend` itself. Module-specific repository behavior (search,
atomic claims, custom queries...) lives in each module's own
`tests/modules/<name>/test_repositories.py` instead.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.category.mappers import to_category_read
from app.modules.category.models import Category
from app.modules.category.repositories_sqlmodel import CategoryRepository


@pytest.fixture
def session(db_engine) -> Generator[Session, None, None]:
    with Session(db_engine) as session:
        yield session


class TestSQLModelBackendCrud:
    def _make_repo(self, session: Session) -> CategoryRepository:
        return CategoryRepository(SQLModelBackend(session, Category, to_category_read))

    def test_create_get_delete_roundtrip(self, session):
        repo = self._make_repo(session)

        category = repo.create({"name": "Fiction"})
        assert category.id is not None

        fetched = repo.get_by_id(category.id)
        assert fetched is not None
        assert fetched.name == "Fiction"

        repo.delete(fetched.id)
        session.flush()
        assert repo.get_by_id(category.id) is None

    def test_get_by_id_missing_returns_none(self, session):
        repo = self._make_repo(session)
        assert repo.get_by_id(uuid.uuid4()) is None

    def test_list_returns_items_and_total(self, session):
        repo = self._make_repo(session)
        for name in ("Fiction", "Sci-Fi", "History"):
            repo.create({"name": name})

        items, total = repo.list(offset=0, limit=2)
        assert total == 3
        assert len(items) == 2

        items, total = repo.list(offset=2, limit=2)
        assert total == 3
        assert len(items) == 1

    def test_update_applies_changes_and_returns_dto(self, session):
        repo = self._make_repo(session)
        category = repo.create({"name": "Fiction"})

        updated = repo.update(category.id, {"description": "Fiction books"})

        assert updated.description == "Fiction books"
        assert updated.name == "Fiction"  # untouched field stays as-is

    def test_update_missing_row_raises_lookup_error(self, session):
        """Contract violation (caller should have checked existence first via
        `get_or_404`) — must still raise under `python -O`, unlike `assert`."""
        repo = self._make_repo(session)

        with pytest.raises(LookupError):
            repo.update(uuid.uuid4(), {"name": "Ghost"})

    def test_get_by_name(self, session):
        repo = self._make_repo(session)
        repo.create({"name": "Fiction"})

        assert repo.get_by_name("Fiction") is not None
        assert repo.get_by_name("does-not-exist") is None
