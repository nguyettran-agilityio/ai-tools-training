"""POST /borrowings/{id}/renew, through the real HTTP API. Overdue loans
can't be produced through the API, so that case is seeded via `db_engine`,
same as `test_lists.py`."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from app.modules.borrowing.models import Borrowing


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


def renew(client, token, auth_headers, borrowing_id):
    return client.post(f"/borrowings/{borrowing_id}/renew", headers=auth_headers(token))


def get_my_id(client, token, auth_headers):
    return client.get("/auth/me", headers=auth_headers(token)).json()["id"]


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def assert_error_body(response, code: str) -> None:
    assert set(response.json()) == {"code", "message", "errors"}
    assert response.json()["code"] == code


@pytest.fixture
def second_member_token(client) -> str:
    email = "member2@example.com"
    password = "supersecret"
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "fullName": "Second Member"},
    )
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


@pytest.fixture
def loan(client, admin_token, member_token, auth_headers):
    """An active, single-copy loan held by `member_token`."""
    book = create_book(client, admin_token, auth_headers, totalCopies=1)
    return borrow(client, member_token, auth_headers, book["id"]).json()


@pytest.fixture
def seed_loan(client, admin_token, member_token, auth_headers, db_engine):
    """Insert a loan for `member_token` with an exact `due_date` — the API
    always sets it to now + loan length, so boundary cases go via the DB."""
    user_id = uuid.UUID(get_my_id(client, member_token, auth_headers))

    def _seed(due_date: datetime) -> uuid.UUID:
        book = create_book(client, admin_token, auth_headers)
        with Session(db_engine) as session:
            borrowing = Borrowing(
                user_id=user_id,
                book_id=uuid.UUID(book["id"]),
                borrowed_at=due_date - timedelta(days=14),
                due_date=due_date,
                returned_at=None,
            )
            session.add(borrowing)
            session.commit()
            return borrowing.id

    return _seed


class TestRenew:
    def test_happy_path_returns_200_and_extends_due_date_by_14_days(
        self, client, member_token, auth_headers, loan
    ):
        response = renew(client, member_token, auth_headers, loan["id"])

        assert response.status_code == 200
        body = response.json()
        assert parse_dt(body["dueDate"]) == parse_dt(loan["dueDate"]) + timedelta(days=14)
        assert body["renewedAt"] is not None
        assert body["status"] == "active"
        assert loan["renewedAt"] is None

    def test_second_renewal_returns_409(self, client, member_token, auth_headers, loan):
        renew(client, member_token, auth_headers, loan["id"])

        response = renew(client, member_token, auth_headers, loan["id"])

        assert response.status_code == 409
        assert_error_body(response, "CONFLICT")
        assert "already been renewed" in response.json()["message"]

    def test_overdue_loan_returns_409(self, client, member_token, auth_headers, seed_loan):
        borrowing_id = seed_loan(due_date=datetime.now(UTC) - timedelta(days=6))

        response = renew(client, member_token, auth_headers, borrowing_id)

        assert response.status_code == 409
        assert_error_body(response, "CONFLICT")
        assert "Overdue" in response.json()["message"]

    def test_due_a_few_seconds_from_now_can_still_be_renewed(
        self, client, member_token, auth_headers, seed_loan
    ):
        due_date = datetime.now(UTC) + timedelta(seconds=5)
        borrowing_id = seed_loan(due_date=due_date)

        response = renew(client, member_token, auth_headers, borrowing_id)

        assert response.status_code == 200
        assert parse_dt(response.json()["dueDate"]) == due_date + timedelta(days=14)

    def test_overdue_by_a_few_seconds_returns_409(
        self, client, member_token, auth_headers, seed_loan
    ):
        borrowing_id = seed_loan(due_date=datetime.now(UTC) - timedelta(seconds=5))

        response = renew(client, member_token, auth_headers, borrowing_id)

        assert response.status_code == 409
        assert_error_body(response, "CONFLICT")
        assert "Overdue" in response.json()["message"]

    def test_another_members_open_reservation_returns_409(
        self, client, member_token, second_member_token, auth_headers, loan
    ):
        # No copy left, so the second member's borrow queues a reservation.
        queued = borrow(client, second_member_token, auth_headers, loan["bookId"])
        assert queued.status_code == 202

        response = renew(client, member_token, auth_headers, loan["id"])

        assert response.status_code == 409
        assert_error_body(response, "CONFLICT")
        assert "open reservation" in response.json()["message"]

    def test_returned_loan_returns_409(self, client, member_token, auth_headers, loan):
        client.post(f"/borrowings/{loan['id']}/return", headers=auth_headers(member_token))

        response = renew(client, member_token, auth_headers, loan["id"])

        assert response.status_code == 409
        assert_error_body(response, "CONFLICT")

    def test_someone_elses_loan_returns_403(self, client, second_member_token, auth_headers, loan):
        response = renew(client, second_member_token, auth_headers, loan["id"])

        assert response.status_code == 403
        assert_error_body(response, "FORBIDDEN")

    def test_unknown_borrowing_returns_404(self, client, member_token, auth_headers):
        response = renew(client, member_token, auth_headers, uuid.uuid4())

        assert response.status_code == 404
        assert_error_body(response, "NOT_FOUND")

    def test_anonymous_returns_401(self, client, loan):
        response = client.post(f"/borrowings/{loan['id']}/renew")

        assert response.status_code == 401
