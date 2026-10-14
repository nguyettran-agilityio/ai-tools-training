from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token, decode_access_token
from app.core.token_denylist import get_token_denylist
from app.modules.user.models import User


def register(client, email="jane@example.com", password="supersecret", full_name="Jane Doe"):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": password, "fullName": full_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email="jane@example.com", password="supersecret"):
    return client.post("/auth/login", json={"email": email, "password": password})


class TestRegister:
    def test_returns_201_with_camel_case_body_and_no_password(self, client):
        response = client.post(
            "/auth/register",
            json={
                "email": "jane@example.com",
                "password": "supersecret",
                "fullName": "Jane Doe",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "jane@example.com"
        assert data["fullName"] == "Jane Doe"
        assert data["role"] == "member"
        assert data["isActive"] is True
        assert "id" in data
        assert "createdAt" in data
        assert "hashedPassword" not in data
        assert "hashed_password" not in data

    def test_duplicate_email_returns_409_conflict(self, client):
        register(client)

        response = client.post(
            "/auth/register",
            json={
                "email": "jane@example.com",
                "password": "anotherpass",
                "fullName": "Jane 2",
            },
        )

        assert response.status_code == 409
        assert response.json()["code"] == "CONFLICT"

    def test_invalid_email_returns_422_validation_error(self, client):
        response = client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "password": "supersecret",
                "fullName": "Jane Doe",
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert any(error["field"] == "email" for error in body["errors"])

    def test_short_password_returns_422_validation_error(self, client):
        response = client.post(
            "/auth/register",
            json={
                "email": "jane@example.com",
                "password": "short",
                "fullName": "Jane Doe",
            },
        )

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert any(error["field"] == "password" for error in body["errors"])


class TestLogin:
    def test_correct_credentials_return_access_token(self, client):
        register(client)

        response = login(client)

        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"]

    def test_wrong_password_returns_401(self, client):
        register(client)

        response = login(client, password="wrongpassword")

        assert response.status_code == 401
        body = response.json()
        assert body["code"] == "UNAUTHORIZED"
        assert body["message"] == "Invalid email or password"

    def test_unknown_email_returns_401_with_same_message(self, client):
        response = login(client, email="nobody@example.com")

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid email or password"

    def test_inactive_user_returns_401_with_same_message(self, client, db_engine):
        register(client)
        with Session(db_engine) as session:
            user = session.exec(select(User).where(User.email == "jane@example.com")).one()
            user.is_active = False
            session.add(user)
            session.commit()

        response = login(client)

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid email or password"


class TestLogout:
    def test_login_then_logout_denylists_the_tokens_jti(self, client):
        register(client)
        token = login(client).json()["access_token"]

        response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 204
        payload = decode_access_token(token)
        assert get_token_denylist().is_denied(payload["jti"]) is True

    def test_missing_token_returns_401(self, client):
        response = client.post("/auth/logout")

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_garbage_token_returns_401(self, client):
        response = client.post("/auth/logout", headers={"Authorization": "Bearer garbage-token"})

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"


class TestTokenExpiry:
    def test_expired_token_maps_to_unauthorized_on_decode(self):
        token = create_access_token(subject="some-user-id", expires_delta=timedelta(seconds=-1))

        with pytest.raises(UnauthorizedError):
            decode_access_token(token)
