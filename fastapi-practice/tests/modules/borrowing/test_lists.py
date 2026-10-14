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


def return_borrowing(client, token, auth_headers, borrowing_id):
    return client.post(f"/borrowings/{borrowing_id}/return", headers=auth_headers(token))


def get_my_id(client, token, auth_headers):
    return client.get("/auth/me", headers=auth_headers(token)).json()["id"]


@pytest.fixture
def second_member_token(client) -> str:
    """A second, distinct member (`member_token` from `conftest.py` is the
    first) so tests can exercise cross-user isolation/aggregation."""
    email = "member2@example.com"
    password = "supersecret"
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "fullName": "Second Member"},
    )
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


class TestHistory:
    def test_shows_all_own_borrowings_newest_first_with_correct_statuses(
        self, client, admin_token, member_token, auth_headers
    ):
        books = [create_book(client, admin_token, auth_headers, totalCopies=1) for _ in range(3)]
        created = [borrow(client, member_token, auth_headers, b["id"]).json() for b in books]
        return_borrowing(client, member_token, auth_headers, created[0]["id"])

        response = client.get("/borrowings/history", headers=auth_headers(member_token))

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        # Newest first == reverse creation order.
        assert [item["id"] for item in data["items"]] == [
            created[2]["id"],
            created[1]["id"],
            created[0]["id"],
        ]
        statuses = {item["id"]: item["status"] for item in data["items"]}
        assert statuses[created[0]["id"]] == "returned"
        assert statuses[created[1]["id"]] == "active"
        assert statuses[created[2]["id"]] == "active"

    def test_does_not_include_other_members_rows(
        self, client, admin_token, member_token, second_member_token, auth_headers
    ):
        book_a = create_book(client, admin_token, auth_headers, totalCopies=1)
        book_b = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrow(client, member_token, auth_headers, book_a["id"])
        borrow(client, second_member_token, auth_headers, book_b["id"])

        response = client.get("/borrowings/history", headers=auth_headers(member_token))

        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["bookId"] == book_a["id"]

    def test_pagination_totals(self, client, admin_token, member_token, auth_headers):
        books = [create_book(client, admin_token, auth_headers, totalCopies=1) for _ in range(3)]
        for book in books:
            borrow(client, member_token, auth_headers, book["id"])

        response = client.get(
            "/borrowings/history",
            params={"page": 1, "pageSize": 2},
            headers=auth_headers(member_token),
        )

        data = response.json()
        assert data["total"] == 3
        assert data["totalPages"] == 2
        assert len(data["items"]) == 2

    def test_anonymous_returns_401(self, client):
        response = client.get("/borrowings/history")

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"


class TestCurrent:
    def test_shows_only_active_borrowings(self, client, admin_token, member_token, auth_headers):
        books = [create_book(client, admin_token, auth_headers, totalCopies=1) for _ in range(3)]
        created = [borrow(client, member_token, auth_headers, b["id"]).json() for b in books]
        return_borrowing(client, member_token, auth_headers, created[0]["id"])

        response = client.get("/borrowings/current", headers=auth_headers(member_token))

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert all(item["status"] == "active" for item in data)
        assert created[0]["id"] not in {item["id"] for item in data}

    def test_empty_after_returning_everything(
        self, client, admin_token, member_token, auth_headers
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        created = borrow(client, member_token, auth_headers, book["id"]).json()
        return_borrowing(client, member_token, auth_headers, created["id"])

        response = client.get("/borrowings/current", headers=auth_headers(member_token))

        assert response.status_code == 200
        assert response.json() == []


class TestOverdue:
    def test_returns_only_active_and_past_due_rows(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        """Also exercises the naive-vs-aware datetime path: rows inserted
        directly go through SQLite and come back with `tzinfo=None` (see
        `app/modules/borrowing/mappers.py`'s `_as_utc`) — this test failing
        with a `TypeError` instead of an assertion failure would mean that
        normalization regressed."""
        book = create_book(client, admin_token, auth_headers, totalCopies=3)
        member_id = uuid.UUID(get_my_id(client, member_token, auth_headers))
        book_id = uuid.UUID(book["id"])
        past = datetime.now(UTC) - timedelta(days=20)
        future = datetime.now(UTC) + timedelta(days=5)

        with Session(db_engine) as session:
            overdue_active = Borrowing(
                user_id=member_id,
                book_id=book_id,
                borrowed_at=past,
                due_date=past + timedelta(days=14),
                returned_at=None,
            )
            overdue_but_returned = Borrowing(
                user_id=member_id,
                book_id=book_id,
                borrowed_at=past,
                due_date=past + timedelta(days=14),
                returned_at=datetime.now(UTC),
            )
            not_yet_due = Borrowing(
                user_id=member_id,
                book_id=book_id,
                borrowed_at=datetime.now(UTC),
                due_date=future,
                returned_at=None,
            )
            session.add_all([overdue_active, overdue_but_returned, not_yet_due])
            session.commit()
            session.refresh(overdue_active)
            expected_id = str(overdue_active.id)

        response = client.get("/borrowings/overdue", headers=auth_headers(admin_token))

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == expected_id
        assert data["items"][0]["status"] == "overdue"

    def test_member_returns_403(self, client, member_token, auth_headers):
        response = client.get("/borrowings/overdue", headers=auth_headers(member_token))

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"


class TestAdminList:
    def test_sees_rows_across_multiple_users(
        self, client, admin_token, member_token, second_member_token, auth_headers
    ):
        book_a = create_book(client, admin_token, auth_headers, totalCopies=1)
        book_b = create_book(client, admin_token, auth_headers, totalCopies=1)
        borrow(client, member_token, auth_headers, book_a["id"])
        borrow(client, second_member_token, auth_headers, book_b["id"])

        response = client.get("/borrowings", headers=auth_headers(admin_token))

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len({item["userId"] for item in data["items"]}) == 2

    def test_overdue_only_matches_overdue_endpoint(
        self, client, admin_token, member_token, auth_headers, db_engine
    ):
        book = create_book(client, admin_token, auth_headers, totalCopies=1)
        member_id = uuid.UUID(get_my_id(client, member_token, auth_headers))
        past = datetime.now(UTC) - timedelta(days=20)

        with Session(db_engine) as session:
            session.add(
                Borrowing(
                    user_id=member_id,
                    book_id=uuid.UUID(book["id"]),
                    borrowed_at=past,
                    due_date=past + timedelta(days=14),
                    returned_at=None,
                )
            )
            session.commit()

        overdue_response = client.get("/borrowings/overdue", headers=auth_headers(admin_token))
        list_response = client.get(
            "/borrowings",
            params={"overdueOnly": True},
            headers=auth_headers(admin_token),
        )

        assert overdue_response.status_code == 200
        assert list_response.status_code == 200
        assert overdue_response.json()["items"] == list_response.json()["items"]

    def test_member_returns_403(self, client, member_token, auth_headers):
        response = client.get("/borrowings", headers=auth_headers(member_token))

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"


class TestRouteOrderGuard:
    """Locks in the house rule from the top of `routers.py`: static routes
    must be matched on their own, never swallowed by a `/{borrowing_id}`
    path-param route declared earlier."""

    def test_history_returns_200_not_a_uuid_parse_error(self, client, member_token, auth_headers):
        response = client.get("/borrowings/history", headers=auth_headers(member_token))

        assert response.status_code == 200
        assert response.status_code != 422

    def test_current_returns_200_not_a_uuid_parse_error(self, client, member_token, auth_headers):
        response = client.get("/borrowings/current", headers=auth_headers(member_token))

        assert response.status_code == 200
        assert response.status_code != 422
