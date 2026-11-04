"""Rate-limit key behind Vercel's proxy (`trust_proxy_headers`).

Behind Vercel the socket peer can be Vercel's own infrastructure, so with
`trust_proxy_headers` on, `rate_limit_auth` keys on `x-vercel-forwarded-for`
instead. Off (the default), the header is ignored so it can't be spoofed.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.deps import rate_limit_auth
from app.main import app

_PAYLOAD = {"email": "nobody@example.com", "password": "wrong-password"}


@pytest.fixture
def rate_limited_client(client):
    """`client` with the real `rate_limit_auth` (the shared fixture bypasses it)."""
    app.dependency_overrides.pop(rate_limit_auth, None)
    yield client
    app.dependency_overrides.pop(get_settings, None)


def _trust_proxy_headers(enabled: bool) -> None:
    settings = get_settings().model_copy(update={"trust_proxy_headers": enabled})
    app.dependency_overrides[get_settings] = lambda: settings


def _exhaust(client, headers: dict[str, str]) -> None:
    for _ in range(get_settings().auth_rate_limit_max_attempts):
        assert client.post("/auth/login", json=_PAYLOAD, headers=headers).status_code == 401


class TestTrustProxyHeadersOn:
    def test_different_forwarded_ips_do_not_share_a_counter(self, rate_limited_client):
        _trust_proxy_headers(True)
        _exhaust(rate_limited_client, {"x-vercel-forwarded-for": "203.0.113.1"})

        blocked = rate_limited_client.post(
            "/auth/login", json=_PAYLOAD, headers={"x-vercel-forwarded-for": "203.0.113.1"}
        )
        other = rate_limited_client.post(
            "/auth/login", json=_PAYLOAD, headers={"x-vercel-forwarded-for": "203.0.113.2"}
        )

        assert blocked.status_code == 429
        assert other.status_code == 401

    def test_uses_first_entry_of_a_forwarded_list(self, rate_limited_client):
        _trust_proxy_headers(True)
        _exhaust(rate_limited_client, {"x-vercel-forwarded-for": "203.0.113.1"})

        blocked = rate_limited_client.post(
            "/auth/login",
            json=_PAYLOAD,
            headers={"x-vercel-forwarded-for": "203.0.113.1, 10.0.0.1"},
        )

        assert blocked.status_code == 429

    def test_falls_back_to_socket_peer_without_the_header(self, rate_limited_client):
        _trust_proxy_headers(True)
        _exhaust(rate_limited_client, {})

        blocked = rate_limited_client.post("/auth/login", json=_PAYLOAD)

        assert blocked.status_code == 429

    @pytest.mark.parametrize("trust", [True, False])
    def test_fallback_keys_on_each_socket_peer(self, rate_limited_client, trust):
        """Without the header, two different socket peers get separate
        counters, so the fallback really is `request.client.host`, not a
        constant."""
        _trust_proxy_headers(trust)
        peer_a = TestClient(app, client=("198.51.100.1", 50000))
        peer_b = TestClient(app, client=("198.51.100.2", 50000))
        _exhaust(peer_a, {})

        assert peer_a.post("/auth/login", json=_PAYLOAD).status_code == 429
        assert peer_b.post("/auth/login", json=_PAYLOAD).status_code == 401


class TestTrustProxyHeadersOff:
    def test_ignores_the_forwarded_header(self, rate_limited_client):
        _trust_proxy_headers(False)
        _exhaust(rate_limited_client, {"x-vercel-forwarded-for": "203.0.113.1"})

        # A spoofed, different header value still hits the same (socket) key.
        blocked = rate_limited_client.post(
            "/auth/login", json=_PAYLOAD, headers={"x-vercel-forwarded-for": "203.0.113.2"}
        )

        assert blocked.status_code == 429

    def test_is_the_default(self):
        # `_env_file=None`: check the code default, not the local `.env`.
        settings = Settings(
            _env_file=None, jwt_secret_key="test-secret-key-with-at-least-32-characters"
        )

        assert settings.trust_proxy_headers is False
