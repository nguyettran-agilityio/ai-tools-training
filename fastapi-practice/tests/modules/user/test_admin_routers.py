"""Admin user-management router/service integration tests, through the real
HTTP API."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.modules.borrowing.models import Borrowing
from app.modules.reservation.models import Reservation


def create_user(client, admin_token, auth_headers, role="member", **overrides):
    payload = {
        "email": f"user-{uuid.uuid4()}@example.com",
        "password": "supersecret",
        "fullName": "Some User",
        "role": role,
    }
    payload.update(overrides)
    return client.post("/users", json=payload, headers=auth_headers(admin_token))


def get_my_id(client, token, auth_headers):
    return client.get("/auth/me", headers=auth_headers(token)).json()["id"]


def seed_book(client, admin_token, auth_headers):
    """A category + book, created via the real API, for borrowing FK rows."""
    category = client.post(
        "/categories", json={"name": f"Cat {uuid.uuid4()}"}, headers=auth_headers(admin_token)
    ).json()
    book = client.post(
        "/books",
        json={
            "title": "Deep Work",
            "author": "Cal Newport",
            "isbn": f"isbn-{uuid.uuid4()}",
            "categoryId": category["id"],
            "totalCopies": 3,
        },
        headers=auth_headers(admin_token),
    ).json()
    return book["id"]


class TestAuthGuards:
    """Every endpoint must reject anonymous (401) and member (403) callers.
    Uses `PATCH /users/{id}` and `GET /users` as representative endpoints —
    all 5 share the same `require_admin` dependency."""

    def test_list_anonymous_401(self, client):
        response = client.get("/users")
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_list_member_403(self, client, member_token, auth_headers):
        response = client.get("/users", headers=auth_headers(member_token))
        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_get_anonymous_401(self, client):
        response = client.get(f"/users/{uuid.uuid4()}")
        assert response.status_code == 401

    def test_get_member_403(self, client, member_token, auth_headers):
        response = client.get(f"/users/{uuid.uuid4()}", headers=auth_headers(member_token))
        assert response.status_code == 403

    def test_create_anonymous_401(self, client):
        response = client.post(
            "/users",
            json={"email": "x@example.com", "password": "supersecret", "fullName": "X"},
        )
        assert response.status_code == 401

    def test_create_member_403(self, client, member_token, auth_headers):
        response = client.post(
            "/users",
            json={"email": "x@example.com", "password": "supersecret", "fullName": "X"},
            headers=auth_headers(member_token),
        )
        assert response.status_code == 403

    def test_patch_anonymous_401(self, client):
        response = client.patch(f"/users/{uuid.uuid4()}", json={"fullName": "X"})
        assert response.status_code == 401

    def test_patch_member_403(self, client, member_token, auth_headers):
        response = client.patch(
            f"/users/{uuid.uuid4()}", json={"fullName": "X"}, headers=auth_headers(member_token)
        )
        assert response.status_code == 403

    def test_delete_anonymous_401(self, client):
        response = client.delete(f"/users/{uuid.uuid4()}")
        assert response.status_code == 401

    def test_delete_member_403(self, client, member_token, auth_headers):
        response = client.delete(f"/users/{uuid.uuid4()}", headers=auth_headers(member_token))
        assert response.status_code == 403


class TestListUsers:
    def test_role_and_is_active_filters_and_pagination(self, client, admin_token, auth_headers):
        for _ in range(3):
            create_user(client, admin_token, auth_headers, role="member")
        create_user(client, admin_token, auth_headers, role="admin")
        inactive = create_user(client, admin_token, auth_headers, role="member").json()
        client.patch(
            f"/users/{inactive['id']}",
            json={"isActive": False},
            headers=auth_headers(admin_token),
        )

        response = client.get(
            "/users", params={"role": "member"}, headers=auth_headers(admin_token)
        )
        assert response.status_code == 200
        data = response.json()
        assert all(item["role"] == "member" for item in data["items"])
        assert data["total"] == 4  # 3 active members + the 1 later deactivated

        response = client.get(
            "/users", params={"isActive": False}, headers=auth_headers(admin_token)
        )
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == inactive["id"]

        response = client.get(
            "/users", params={"page": 1, "pageSize": 2}, headers=auth_headers(admin_token)
        )
        data = response.json()
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["pageSize"] == 2

    def test_response_never_contains_hashed_password(self, client, admin_token, auth_headers):
        create_user(client, admin_token, auth_headers)

        response = client.get("/users", headers=auth_headers(admin_token))

        assert "hashedPassword" not in response.text
        assert "hashed_password" not in response.text


class TestCreateUser:
    def test_create_member(self, client, admin_token, auth_headers):
        response = create_user(client, admin_token, auth_headers, role="member")

        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "member"
        assert "hashedPassword" not in response.text

    def test_create_admin_via_role_field(self, client, admin_token, auth_headers):
        response = create_user(client, admin_token, auth_headers, role="admin")

        assert response.status_code == 201
        assert response.json()["role"] == "admin"

    def test_duplicate_email_returns_409(self, client, admin_token, auth_headers):
        email = f"dup-{uuid.uuid4()}@example.com"
        create_user(client, admin_token, auth_headers, email=email)

        response = create_user(client, admin_token, auth_headers, email=email)

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_short_password_returns_422(self, client, admin_token, auth_headers):
        response = create_user(client, admin_token, auth_headers, password="short")

        assert response.status_code == 422


class TestUpdateUser:
    def test_admin_deactivates_another_user(self, client, admin_token, auth_headers):
        other = create_user(client, admin_token, auth_headers).json()

        response = client.patch(
            f"/users/{other['id']}",
            json={"isActive": False},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 200
        assert response.json()["isActive"] is False

    def test_admin_deactivating_self_returns_400(self, client, admin_token, auth_headers):
        my_id = get_my_id(client, admin_token, auth_headers)

        response = client.patch(
            f"/users/{my_id}",
            json={"isActive": False},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "BAD_REQUEST"

    def test_admin_demoting_self_returns_400(self, client, admin_token, auth_headers):
        my_id = get_my_id(client, admin_token, auth_headers)

        response = client.patch(
            f"/users/{my_id}",
            json={"role": "member"},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 400
        assert response.json()["code"] == "BAD_REQUEST"


class TestDeleteUser:
    def test_another_user_with_no_borrowings_returns_204(self, client, admin_token, auth_headers):
        other = create_user(client, admin_token, auth_headers).json()

        response = client.delete(f"/users/{other['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 204
        assert response.content == b""

    def test_self_delete_returns_400(self, client, admin_token, auth_headers):
        my_id = get_my_id(client, admin_token, auth_headers)

        response = client.delete(f"/users/{my_id}", headers=auth_headers(admin_token))

        assert response.status_code == 400
        assert response.json()["code"] == "BAD_REQUEST"

    def test_user_with_active_borrowing_returns_409(
        self, client, admin_token, auth_headers, db_engine
    ):
        other = create_user(client, admin_token, auth_headers).json()
        book_id = uuid.UUID(seed_book(client, admin_token, auth_headers))

        with Session(db_engine) as session:
            session.add(
                Borrowing(
                    user_id=uuid.UUID(other["id"]),
                    book_id=book_id,
                    borrowed_at=datetime.now(UTC),
                    due_date=datetime.now(UTC) + timedelta(days=14),
                    returned_at=None,
                )
            )
            session.commit()

        response = client.delete(f"/users/{other['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_user_with_only_returned_borrowing_returns_204(
        self, client, admin_token, auth_headers, db_engine
    ):
        other = create_user(client, admin_token, auth_headers).json()
        book_id = uuid.UUID(seed_book(client, admin_token, auth_headers))

        with Session(db_engine) as session:
            borrowed_at = datetime.now(UTC) - timedelta(days=20)
            session.add(
                Borrowing(
                    user_id=uuid.UUID(other["id"]),
                    book_id=book_id,
                    borrowed_at=borrowed_at,
                    due_date=borrowed_at + timedelta(days=14),
                    returned_at=datetime.now(UTC),
                )
            )
            session.commit()

        response = client.delete(f"/users/{other['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 204

    def test_user_with_open_reservation_returns_409(
        self, client, admin_token, auth_headers, db_engine
    ):
        other = create_user(client, admin_token, auth_headers).json()
        book_id = uuid.UUID(seed_book(client, admin_token, auth_headers))

        with Session(db_engine) as session:
            session.add(Reservation(user_id=uuid.UUID(other["id"]), book_id=book_id))
            session.commit()

        response = client.delete(f"/users/{other['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"


class TestDeactivatedUserCannotLogin:
    def test_deactivated_user_login_returns_401(self, client, admin_token, auth_headers):
        email = f"deactivate-{uuid.uuid4()}@example.com"
        password = "supersecret"
        created = create_user(
            client, admin_token, auth_headers, email=email, password=password
        ).json()

        client.patch(
            f"/users/{created['id']}",
            json={"isActive": False},
            headers=auth_headers(admin_token),
        )

        response = client.post("/auth/login", json={"email": email, "password": password})

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"
