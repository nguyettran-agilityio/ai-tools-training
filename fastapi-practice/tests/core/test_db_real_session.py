"""Integration tests for the REAL `get_session`/`session_scope` in
`app/core/db.py`.

Every other test in this suite goes through `tests/conftest.py`'s `client`
fixture, which overrides the `get_session` dependency with a hand-written
duplicate bound to an in-memory engine — so the actual commit/rollback
transaction boundary in `app/core/db.py` is never executed anywhere else.

These two tests deliberately do NOT use that override. Instead they point
the module-level `app.core.db.engine` at a throwaway file-based SQLite
database (via `monkeypatch`, reverted automatically after each test) and
drive requests through the unmodified `get_session` dependency, so a real
`session.commit()` / `session.rollback()` actually run.
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.core import db as db_module
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.main import app
from app.modules.user.models import User


@pytest.fixture
def real_db_client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    """`TestClient` over the real `app`, with `app.core.db.engine` repointed
    at a throwaway file-based SQLite database under pytest's per-test
    `tmp_path` (auto-cleaned by pytest — never touches `library.db`).

    No `get_session` dependency override here — requests run through the
    real `session_scope()` / `get_session()` in `app/core/db.py`.
    """
    db_path = tmp_path / "integration.db"
    real_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(real_engine)
    monkeypatch.setattr(db_module, "engine", real_engine)

    # `raise_server_exceptions=False` so an unhandled exception that our own
    # global handler already turned into a 500 response comes back as a
    # normal response instead of re-raising in the test process — same
    # reasoning as tests/test_exception_handler.py's throwaway client.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    real_engine.dispose()


def _fetch_user_by_email(email: str) -> User | None:
    """Fresh session/connection against the same on-disk file, independent
    of whatever session the request used — the only way to prove a row was
    actually committed to disk rather than merely visible within the
    request's own (still-open) session."""
    with Session(db_module.engine) as verify_session:
        return verify_session.exec(select(User).where(User.email == email)).first()


class TestRealCommitPath:
    def test_register_persists_a_real_row_after_commit(self, real_db_client):
        """A normal request that creates a row must actually persist after
        the request completes, proving the real `session.commit()` in
        `session_scope()` runs — not just its hand-written test stand-in."""
        email = "real-commit@example.com"

        response = real_db_client.post(
            "/auth/register",
            json={"email": email, "password": "supersecret1", "fullName": "Real Commit"},
        )

        assert response.status_code == 201, response.text
        user = _fetch_user_by_email(email)
        assert user is not None
        assert user.full_name == "Real Commit"


class TestRealRollbackPath:
    def test_failed_request_rolls_back_and_persists_nothing(self, real_db_client, monkeypatch):
        """Force an error AFTER `AuthService.register` has already flushed
        the new user to the transaction, but before the request completes,
        so `session_scope()`'s `except Exception: session.rollback()` branch
        runs. The flushed-but-uncommitted row must not survive."""
        email = "real-rollback@example.com"

        def _boom(*_args, **_kwargs):
            raise RuntimeError("simulated failure after the DB write was flushed")

        # Patch the name as looked up in `core/deps.py` (this project's
        # `@patch("polls.views.X")`-style convention) — the repository's
        # `create()` flushes the new row and then calls `to_dto` (bound to
        # `to_user_read` here) to build the response DTO, so patching it
        # fails AFTER the DB write was flushed but before the request/
        # response cycle completes and `session_scope()` commits.
        monkeypatch.setattr("app.core.deps.to_user_read", _boom)

        response = real_db_client.post(
            "/auth/register",
            json={"email": email, "password": "supersecret1", "fullName": "Real Rollback"},
        )

        assert response.status_code == 500
        assert _fetch_user_by_email(email) is None
