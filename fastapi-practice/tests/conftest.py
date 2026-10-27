"""Shared pytest fixtures."""

from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.db import get_session
from app.core.deps import rate_limit_auth
from app.core.rate_limiter import get_rate_limiter
from app.core.security import hash_password
from app.main import app
from app.modules.user.models import User, UserRole


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Belt-and-suspenders alongside the `client` fixture's override below —
    keeps the process-wide limiter's state from leaking into a test that
    exercises it directly against a fresh `InMemoryRateLimiter` instance."""
    get_rate_limiter().reset()
    yield


@pytest.fixture
def db_engine():
    """In-memory SQLite engine (`StaticPool`), shared by the `client` fixture's
    `get_session` override — exposed separately so tests can also open their
    own `Session(db_engine)` to set up rows the API can't produce directly
    (e.g. an inactive user)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
    """`TestClient` over `app`, with the `get_session` dependency overridden
    to `db_engine` — same pattern as
    `fastapi/examples/auth-crud-api/test_main.py` — so tests never touch
    `library.db`.
    """

    def override_get_session() -> Generator[Session, None, None]:
        # Same commit-on-success / rollback-on-exception contract as the
        # real `get_session` (see `app/core/db.py`).
        with Session(db_engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session
    # `TestClient` requests all share one "client IP", so most tests (which
    # aren't testing rate limiting itself, but do register/login several
    # distinct users per test) would trip each other's limit. Bypassed here
    # by default; `test_rate_limiting.py` removes this override to test the
    # real thing.
    app.dependency_overrides[rate_limit_auth] = lambda: None
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(rate_limit_auth, None)


@pytest.fixture
def member_token(client: TestClient) -> str:
    """Registers a fresh member (via the real `/auth/register` endpoint, so
    it's a normal, active member) and returns a valid access token for them."""
    email = "member@example.com"
    password = "supersecret"
    client.post(
        "/auth/register",
        json={"email": email, "password": password, "fullName": "Member User"},
    )
    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


@pytest.fixture
def admin_token(client: TestClient, db_engine) -> str:
    """Creates an admin directly in the DB — `/auth/register` always creates
    a member (see `AuthService.register`), so there's no API route that
    produces one — then returns a valid access token for them."""
    email = "admin@example.com"
    password = "supersecret"
    with Session(db_engine) as session:
        session.add(
            User(
                email=email,
                hashed_password=hash_password(password),
                full_name="Admin User",
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        session.commit()

    response = client.post("/auth/login", json={"email": email, "password": password})
    return str(response.json()["access_token"])


@pytest.fixture
def auth_headers() -> Callable[[str], dict[str, str]]:
    """`auth_headers(token)` -> `{"Authorization": "Bearer <token>"}`, for
    `client.get(url, headers=auth_headers(token))`."""

    def _auth_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers
