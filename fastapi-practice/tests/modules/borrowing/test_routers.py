"""Borrowing router/service integration tests, through the real HTTP API."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.borrowing.mappers import to_borrowing_read
from app.modules.borrowing.models import Borrowing
from app.modules.borrowing.repositories_sqlmodel import BorrowingRepository


def create_category(client, token, auth_headers, name=None):
    name = name or f"Cat {uuid.uuid4()}"
    response = client.post("/categories", json={"name": name}, headers=auth_headers(token))
    return response.json()["id"]


def create_book(client, admin_token, auth_headers, **overrides):
    category_id = overrides.pop("category_id", None) or create_category(
        client, admin_token, auth_headers
    )
    payload = {
        "title": "Clean Code",
        "author": "Robert C. Martin",
        "isbn": f"isbn-{uuid.uuid4()}",
        "categoryId": category_id,
        "totalCopies": 1,
    }
    payload.update(overrides)
    response = client.post("/books", json=payload, headers=auth_headers(admin_token))
    return response.json()


def borrow(client, token, auth_headers, book_id):
    return client.post("/borrowings", json={"bookId": book_id}, headers=auth_headers(token))


def return_borrowing(client, token, auth_headers, borrowing_id):
    return client.post(f"/borrowings/{borrowing_id}/return", headers=auth_headers(token))


@pytest.fixture
def second_member_token(client) -> str:
    """A second, distinct member (`member_token` from `conftest.py` is the
    first) so tests can exercise "someone else's borrowing"."""
    email = "member2@example.com"
    password = "supersecret"
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "fullName": "Second Member"},
    )
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


class TestBorrowBook:
    def test_happy_path_returns_201_active_status_and_due_date_14_days_out(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)

        response = borrow(client, member_token, auth_headers, book["id"])

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "active"
        assert data["returnedAt"] is None
        assert data["bookId"] == book["id"]

        borrowed_at = datetime.fromisoformat(data["borrowedAt"])
        due_date = datetime.fromisoformat(data["dueDate"])
        assert due_date == borrowed_at + timedelta(days=14)

        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 0

    def test_unknown_book_returns_404(self, client, member_token, auth_headers):
        response = borrow(client, member_token, auth_headers, str(uuid.uuid4()))

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_anonymous_returns_401(self, client, admin_token, auth_headers):
        book = create_book(client, admin_token, auth_headers)

        response = client.post("/borrowings", json={"bookId": book["id"]})

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_zero_available_copies_auto_reserves_then_succeeds_after_a_return(
        self, client, admin_token, member_token, second_member_token, auth_headers
    ):
        """Borrowing an out-of-stock book is no longer a hard 409 — it's the
        race-condition safety net: the caller is auto-queued instead. See
        `tests/test_borrow_auto_reserve.py` for the dedicated coverage of
        that behavior; this test just confirms the older "then succeeds
        after a return" flow still ends the same way once the book is free
        again."""
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        first = borrow(client, member_token, auth_headers, book["id"])
        assert first.status_code == 201

        queued = borrow(client, second_member_token, auth_headers, book["id"])
        assert queued.status_code == 202
        assert queued.json()["status"] == "pending"

        return_borrowing(client, member_token, auth_headers, first.json()["id"])

        retried = borrow(client, second_member_token, auth_headers, book["id"])
        assert retried.status_code == 201

    def test_same_member_same_book_twice_returns_409(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=5)
        borrow(client, member_token, auth_headers, book["id"])

        response = borrow(client, member_token, auth_headers, book["id"])

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_sixth_distinct_book_returns_409_then_succeeds_after_a_return(
        self, client, admin_token, member_token, auth_headers
    ):
        books = [create_book(client, admin_token, auth_headers, totalCopies=1) for _ in range(6)]

        borrowed_ids = []
        for book in books[:5]:
            response = borrow(client, member_token, auth_headers, book["id"])
            assert response.status_code == 201
            borrowed_ids.append(response.json()["id"])

        sixth = borrow(client, member_token, auth_headers, books[5]["id"])
        assert sixth.status_code == 409
        assert "borrow limit" in sixth.json()["message"].lower()

        return_borrowing(client, member_token, auth_headers, borrowed_ids[0])

        retried = borrow(client, member_token, auth_headers, books[5]["id"])
        assert retried.status_code == 201


class TestReturnBook:
    def test_happy_path_returns_200_returned_status_and_restores_copies(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        created = borrow(client, member_token, auth_headers, book["id"]).json()

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "returned"
        assert data["returnedAt"] is not None

        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 1

    def test_returning_twice_returns_409(self, client, admin_token, member_token, auth_headers):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        created = borrow(client, member_token, auth_headers, book["id"]).json()
        return_borrowing(client, member_token, auth_headers, created["id"])

        response = return_borrowing(client, member_token, auth_headers, created["id"])

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_returning_someone_elses_borrowing_returns_403(
        self, client, admin_token, member_token, second_member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        created = borrow(client, member_token, auth_headers, book["id"]).json()

        response = return_borrowing(client, second_member_token, auth_headers, created["id"])

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_unknown_borrowing_id_returns_404(self, client, member_token, auth_headers):
        response = return_borrowing(client, member_token, auth_headers, str(uuid.uuid4()))

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


class TestOverdueVisibility:
    def test_past_due_date_computes_overdue_status(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """Minimal check that an unreturned, past-due `Borrowing` reads back
        as "overdue" — full `/borrowings/overdue` listing is a later task."""
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        me = client.get("/auth/me", headers=auth_headers(member_token)).json()

        borrowed_at = datetime.now(UTC) - timedelta(days=20)
        with Session(db_engine) as session:
            session.add(
                Borrowing(
                    user_id=uuid.UUID(me["id"]),
                    book_id=uuid.UUID(book["id"]),
                    borrowed_at=borrowed_at,
                    due_date=borrowed_at + timedelta(days=14),
                    returned_at=None,
                )
            )
            session.commit()

        with Session(db_engine) as session:
            repo = BorrowingRepository(SQLModelBackend(session, Borrowing, to_borrowing_read))
            [result] = repo.list_active_by_user(uuid.UUID(me["id"]))

        assert result.status == "overdue"


class TestAtomicity:
    def test_failed_borrowing_insert_rolls_back_the_book_decrement(
        self, client, admin_token, member_token, auth_headers, monkeypatch
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)

        def _raise(self, data):
            raise RuntimeError("simulated failure after the book decrement")

        monkeypatch.setattr(BorrowingRepository, "create", _raise)

        with pytest.raises(RuntimeError):
            borrow(client, member_token, auth_headers, book["id"])

        # `TestClient` re-raises server exceptions by default, so the
        # request above never got to send a response — check the DB state
        # directly instead of via a second HTTP call.
        book_after = client.get(f"/books/{book['id']}").json()
        assert book_after["availableCopies"] == 1
