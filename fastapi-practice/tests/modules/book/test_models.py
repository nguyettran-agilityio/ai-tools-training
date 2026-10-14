"""Book model round-trip and constraint tests, against an in-memory SQLite DB.

Uses the shared `db_engine` fixture (see `tests/conftest.py`) plus a local
`session` fixture, matching the pattern used across `tests/modules/*/test_models.py`.
"""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.modules.book.models import Book
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


def make_book(session: Session, category_id: uuid.UUID, **overrides) -> Book:
    defaults = {
        "title": "Deep Work",
        "author": "Cal Newport",
        "isbn": f"isbn-{uuid.uuid4()}",
        "category_id": category_id,
        "total_copies": 3,
        "available_copies": 3,
    }
    defaults.update(overrides)
    book = Book(**defaults)
    session.add(book)
    session.commit()
    session.refresh(book)
    return book


class TestBookModel:
    def test_insert_and_round_trip(self, session):
        category = make_category(session)
        book = make_book(session, category_id=category.id, isbn="978-0-13-468599-1")

        fetched = session.get(Book, book.id)
        assert fetched is not None
        assert fetched.isbn == "978-0-13-468599-1"
        assert fetched.category_id == category.id
        assert fetched.available_copies == 3

    def test_duplicate_isbn_raises_integrity_error(self, session):
        category = make_category(session)
        make_book(session, category_id=category.id, isbn="dup-isbn")
        session.add(
            Book(
                title="Another",
                author="Someone",
                isbn="dup-isbn",
                category_id=category.id,
                total_copies=1,
                available_copies=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    def test_nonexistent_category_id_raises_integrity_error(self, session):
        session.add(
            Book(
                title="Orphan Book",
                author="No One",
                isbn="orphan-isbn",
                category_id=uuid.uuid4(),
                total_copies=1,
                available_copies=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    def test_has_no_status_column(self):
        assert "status" not in Book.model_fields
