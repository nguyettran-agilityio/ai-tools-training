"""Tests for `app/core/deps.py` (`get_current_user`, `require_admin`) via
`GET /auth/me`, `POST /auth/logout`, and a throwaway admin-only test route.

Uses the `client`/`db_engine`/`member_token`/`admin_token`/`auth_headers`
fixtures from `conftest.py`.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.core.deps import require_admin
from app.core.security import create_access_token
from app.main import app
from app.modules.user.models import User
from app.modules.user.schemas import UserRead

# ── Throwaway admin-only route, to prove `require_admin` end to end without
# adding a real admin endpoint (that's a later epic's job) ──────────────────

_ADMIN_ONLY_PATH = "/test-only/admin-check"
_test_router = APIRouter()


@_test_router.get(_ADMIN_ONLY_PATH)
def _admin_only(current_user: UserRead = Depends(require_admin)) -> dict:
    return {"email": current_user.email}


app.include_router(_test_router)


class TestMeRequiresAuthentication:
    def test_without_header_returns_401_in_our_error_format(self, client):
        response = client.get("/auth/me")

        assert response.status_code == 401
        body = response.json()
        assert body["code"] == "UNAUTHORIZED"
        assert body["message"] == "Not authenticated"
        # Not HTTPBearer's default `{"detail": "Not authenticated"}` body.
        assert "detail" not in body

    def test_with_garbage_token_returns_401(self, client, auth_headers):
        response = client.get("/auth/me", headers=auth_headers("garbage-token"))

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    def test_with_expired_token_returns_401(self, client, auth_headers):
        token = create_access_token(
            subject="00000000-0000-0000-0000-000000000000", expires_delta=timedelta(seconds=-1)
        )

        response = client.get("/auth/me", headers=auth_headers(token))

        assert response.status_code == 401


class TestLoginMeLogoutFlow:
    def test_login_then_me_returns_current_user(self, client, auth_headers):
        email, password = "flow@example.com", "supersecret"
        client.post(
            "/auth/register",
            json={"email": email, "password": password, "fullName": "Flow User"},
        )
        token = client.post("/auth/login", json={"email": email, "password": password}).json()[
            "access_token"
        ]

        response = client.get("/auth/me", headers=auth_headers(token))

        assert response.status_code == 200
        body = response.json()
        assert body["email"] == email
        assert "hashedPassword" not in body

    def test_logout_then_me_returns_401_token_revoked(self, client, auth_headers):
        email, password = "flow2@example.com", "supersecret"
        client.post(
            "/auth/register",
            json={"email": email, "password": password, "fullName": "Flow User"},
        )
        token = client.post("/auth/login", json={"email": email, "password": password}).json()[
            "access_token"
        ]

        logout_response = client.post("/auth/logout", headers=auth_headers(token))
        assert logout_response.status_code == 204

        me_response = client.get("/auth/me", headers=auth_headers(token))
        assert me_response.status_code == 401
        assert me_response.json()["message"] == "Token has been revoked"


class TestMeWithInactiveUser:
    def test_deactivated_user_returns_401(self, client, db_engine, auth_headers):
        email, password = "inactive@example.com", "supersecret"
        client.post(
            "/auth/register",
            json={"email": email, "password": password, "fullName": "Inactive User"},
        )
        token = client.post("/auth/login", json={"email": email, "password": password}).json()[
            "access_token"
        ]

        with Session(db_engine) as session:
            user = session.exec(select(User).where(User.email == email)).one()
            user.is_active = False
            session.add(user)
            session.commit()

        response = client.get("/auth/me", headers=auth_headers(token))

        assert response.status_code == 401
        assert response.json()["message"] == "Inactive user"


class TestRequireAdmin:
    def test_member_token_is_forbidden(self, client, member_token, auth_headers):
        response = client.get(_ADMIN_ONLY_PATH, headers=auth_headers(member_token))

        assert response.status_code == 403
        assert response.json()["code"] == "FORBIDDEN"

    def test_admin_token_is_allowed(self, client, admin_token, auth_headers):
        response = client.get(_ADMIN_ONLY_PATH, headers=auth_headers(admin_token))

        assert response.status_code == 200
        assert response.json()["email"] == "admin@example.com"

    def test_missing_token_is_unauthorized_not_forbidden(self, client):
        response = client.get(_ADMIN_ONLY_PATH)

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"
