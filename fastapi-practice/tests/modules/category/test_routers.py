"""Category router/service integration tests, through the real HTTP API."""

import uuid

from sqlmodel import Session

from app.modules.book.models import Book


def create_category(client, token, auth_headers, name="Fiction", description=None):
    return client.post(
        "/categories",
        json={"name": name, "description": description},
        headers=auth_headers(token),
    )


class TestListCategories:
    def test_empty_returns_no_items(self, client):
        response = client.get("/categories")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["totalPages"] == 0

    def test_pagination_second_page_and_camel_case_keys(self, client, admin_token, auth_headers):
        for i in range(12):
            create_category(client, admin_token, auth_headers, name=f"Category {i}")

        response = client.get("/categories", params={"page": 2, "pageSize": 5})

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5
        assert data["total"] == 12
        assert data["totalPages"] == 3
        assert data["page"] == 2
        assert data["pageSize"] == 5
        first_item = data["items"][0]
        assert "createdAt" in first_item
        assert "created_at" not in first_item

    def test_no_auth_required(self, client):
        response = client.get("/categories")
        assert response.status_code == 200


class TestGetCategory:
    def test_existing_category_returns_200(self, client, admin_token, auth_headers):
        created = create_category(client, admin_token, auth_headers).json()

        response = client.get(f"/categories/{created['id']}")

        assert response.status_code == 200
        assert response.json()["name"] == "Fiction"

    def test_missing_category_returns_404_not_found(self, client):
        response = client.get(f"/categories/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_malformed_uuid_returns_422(self, client):
        response = client.get("/categories/not-a-uuid")

        assert response.status_code == 422


class TestCreateCategory:
    def test_as_admin_returns_201(self, client, admin_token, auth_headers):
        response = create_category(client, admin_token, auth_headers)

        assert response.status_code == 201
        assert response.json()["name"] == "Fiction"

    def test_as_member_returns_403_forbidden(self, client, member_token, auth_headers):
        response = create_category(client, member_token, auth_headers)

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_anonymous_returns_401_unauthorized(self, client):
        response = client.post("/categories", json={"name": "Fiction"})

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_duplicate_name_returns_409_conflict(self, client, admin_token, auth_headers):
        create_category(client, admin_token, auth_headers)

        response = create_category(client, admin_token, auth_headers)

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_empty_name_returns_422(self, client, admin_token, auth_headers):
        response = client.post("/categories", json={"name": ""}, headers=auth_headers(admin_token))

        assert response.status_code == 422


class TestUpdateCategory:
    def test_partial_update_keeps_existing_name(self, client, admin_token, auth_headers):
        created = create_category(client, admin_token, auth_headers, name="Fiction").json()

        response = client.patch(
            f"/categories/{created['id']}",
            json={"description": "Fiction books"},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Fiction"
        assert data["description"] == "Fiction books"

    def test_rename_to_existing_name_returns_409(self, client, admin_token, auth_headers):
        create_category(client, admin_token, auth_headers, name="Fiction")
        other = create_category(client, admin_token, auth_headers, name="History").json()

        response = client.patch(
            f"/categories/{other['id']}",
            json={"name": "Fiction"},
            headers=auth_headers(admin_token),
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"


class TestDeleteCategory:
    def test_unused_category_returns_204_and_then_404(self, client, admin_token, auth_headers):
        created = create_category(client, admin_token, auth_headers).json()

        response = client.delete(f"/categories/{created['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 204
        assert response.content == b""

        follow_up = client.get(f"/categories/{created['id']}")
        assert follow_up.status_code == 404

    def test_category_with_a_book_returns_409_conflict(
        self, client, admin_token, auth_headers, db_engine
    ):
        created = create_category(client, admin_token, auth_headers).json()
        category_id = uuid.UUID(created["id"])

        with Session(db_engine) as session:
            session.add(
                Book(
                    title="Deep Work",
                    author="Cal Newport",
                    isbn=f"isbn-{uuid.uuid4()}",
                    category_id=category_id,
                    total_copies=1,
                    available_copies=1,
                )
            )
            session.commit()

        response = client.delete(f"/categories/{created['id']}", headers=auth_headers(admin_token))

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"
