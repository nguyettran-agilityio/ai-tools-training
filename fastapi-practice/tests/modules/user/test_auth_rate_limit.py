"""`/auth/login`/`/auth/register` rate limiting, through the real HTTP API.

The `client` fixture bypasses `rate_limit_auth` by default (see
`conftest.py`) so the rest of the suite can freely register/login several
users per test — re-enabled here to test the real thing.
"""

import uuid

from app.core.config import get_settings
from app.core.deps import rate_limit_auth
from app.main import app


def _enable_rate_limiting(client):
    app.dependency_overrides.pop(rate_limit_auth, None)


class TestLoginRateLimit:
    def test_blocks_after_max_attempts_from_the_same_client(self, client):
        _enable_rate_limiting(client)
        max_attempts = get_settings().auth_rate_limit_max_attempts
        payload = {"email": "nobody@example.com", "password": "wrong-password"}

        for _ in range(max_attempts):
            response = client.post("/auth/login", json=payload)
            assert response.status_code == 401  # wrong credentials, but not yet rate-limited

        blocked = client.post("/auth/login", json=payload)
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "TOO_MANY_REQUESTS"


class TestRegisterRateLimit:
    def test_blocks_after_max_attempts_from_the_same_client(self, client):
        _enable_rate_limiting(client)
        max_attempts = get_settings().auth_rate_limit_max_attempts

        for _ in range(max_attempts):
            response = client.post(
                "/auth/register",
                json={
                    "email": f"{uuid.uuid4()}@example.com",
                    "password": "supersecret",
                    "fullName": "Someone",
                },
            )
            assert response.status_code == 201

        blocked = client.post(
            "/auth/register",
            json={
                "email": f"{uuid.uuid4()}@example.com",
                "password": "supersecret",
                "fullName": "X",
            },
        )
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "TOO_MANY_REQUESTS"
