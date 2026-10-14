"""BookRepository tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator

import pytest
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.book.mappers import to_book_read
from app.modules.book.models import Book
from app.modules.book.repositories_sqlmodel import BookRepository
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
    session.flush()
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
    session.flush()
    session.refresh(book)
    return book


class TestBookRepositorySearch:
    @pytest.fixture(autouse=True)
    def _seed(self, session):
        self.fiction = make_category(session, name="Fiction")
        self.history = make_category(session, name="History")
        self.repo = BookRepository(SQLModelBackend(session, Book, to_book_read))

        make_book(session, category_id=self.fiction.id, title="Deep Work", author="Cal Newport")
        make_book(session, category_id=self.fiction.id, title="Atomic Habits", author="James Clear")
        make_book(session, category_id=self.fiction.id, title="The Hobbit", author="J.R.R. Tolkien")
        make_book(session, category_id=self.history.id, title="Sapiens", author="Yuval Noah Harari")
        make_book(session, category_id=self.history.id, title="Deep History", author="Someone Else")

    def test_no_filter_returns_all(self):
        items, total = self.repo.search(query=None, category_id=None, offset=0, limit=10)
        assert total == 5
        assert len(items) == 5

    def test_query_only_matches_title_or_author_case_insensitive(self):
        items, total = self.repo.search(query="deep", category_id=None, offset=0, limit=10)
        assert total == 2
        assert {b.title for b in items} == {"Deep Work", "Deep History"}

        items, total = self.repo.search(query="TOLKIEN", category_id=None, offset=0, limit=10)
        assert total == 1
        assert items[0].title == "The Hobbit"

    def test_category_only(self):
        items, total = self.repo.search(query=None, category_id=self.history.id, offset=0, limit=10)
        assert total == 2
        assert {b.title for b in items} == {"Sapiens", "Deep History"}

    def test_query_and_category_combined(self):
        items, total = self.repo.search(
            query="deep", category_id=self.history.id, offset=0, limit=10
        )
        assert total == 1
        assert items[0].title == "Deep History"

    def test_count_is_a_real_count_not_len_of_page(self):
        _items, total = self.repo.search(query=None, category_id=None, offset=0, limit=2)
        assert total == 5

    def test_get_by_isbn_and_count_by_category(self, session):
        book = make_book(session, category_id=self.fiction.id, isbn="unique-isbn")
        assert self.repo.get_by_isbn("unique-isbn").id == book.id
        assert self.repo.get_by_isbn("does-not-exist") is None
        assert self.repo.count_by_category(self.fiction.id) == 4  # 3 seeded + this one


class TestBookRepositoryAvailableCopiesClaim:
    """`try_decrement_available_copies` is an atomic conditional UPDATE, not
    a Python read-then-write — these tests pin down that it only succeeds
    while a copy is actually there to take, which is what makes two callers
    racing for the last copy safe (see `BorrowingService.borrow`)."""

    @pytest.fixture(autouse=True)
    def _seed(self, session):
        self.session = session
        self.repo = BookRepository(SQLModelBackend(session, Book, to_book_read))
        category = make_category(session)
        self.book = make_book(session, category_id=category.id, total_copies=1, available_copies=1)

    def test_claim_on_last_copy_succeeds_and_decrements(self):
        claimed = self.repo.try_decrement_available_copies(self.book.id)

        assert claimed is True
        self.session.refresh(self.book)
        assert self.book.available_copies == 0

    def test_second_claim_after_copies_exhausted_fails_and_does_not_go_negative(self):
        """Simulates An and Bình racing for the same last copy: the second
        `try_decrement_available_copies` call — made only after the first
        has already committed its UPDATE — must fail rather than silently
        drive `available_copies` below zero."""
        first = self.repo.try_decrement_available_copies(self.book.id)
        second = self.repo.try_decrement_available_copies(self.book.id)

        assert first is True
        assert second is False
        self.session.refresh(self.book)
        assert self.book.available_copies == 0

    def test_claim_on_book_with_no_copies_left_fails(self):
        self.book.available_copies = 0
        self.session.add(self.book)
        self.session.flush()

        assert self.repo.try_decrement_available_copies(self.book.id) is False

    def test_increment_caps_at_total_copies(self):
        self.book.available_copies = 0
        self.session.add(self.book)
        self.session.flush()

        self.repo.increment_available_copies(self.book.id)
        self.session.refresh(self.book)
        assert self.book.available_copies == 1  # capped at total_copies=1

        # A second return (e.g. a duplicate/late notification) must not
        # push it past total_copies.
        self.repo.increment_available_copies(self.book.id)
        self.session.refresh(self.book)
        assert self.book.available_copies == 1
