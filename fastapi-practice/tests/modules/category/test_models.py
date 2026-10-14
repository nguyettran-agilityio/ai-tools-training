"""Category model round-trip and constraint tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.modules.category.models import Category


@pytest.fixture
def session(db_engine) -> Generator[Session, None, None]:
    with Session(db_engine) as session:
        yield session


def make_category(session: Session, **overrides) -> Category:
    defaults = {"name": f"Category {uuid.uuid4()}"}
    defaults.update(overrides)
    category = Category(**defaults)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


class TestCategoryModel:
    def test_insert_and_round_trip(self, session):
        category = make_category(session, name="Fiction", description="Fiction books")

        fetched = session.get(Category, category.id)
        assert fetched is not None
        assert fetched.name == "Fiction"
        assert fetched.description == "Fiction books"

    def test_duplicate_name_raises_integrity_error(self, session):
        make_category(session, name="Sci-Fi")
        session.add(Category(name="Sci-Fi"))
        with pytest.raises(IntegrityError):
            session.commit()
