"""Tests for app/cli/seed_admin.py's core logic (seed_admin()), isolated
from argparse/env/prompts and from the real DB — same in-memory SQLite
pattern as tests/test_models.py.
"""

from collections.abc import Generator

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.cli.seed_admin import AdminAlreadyExistsError, is_valid_email, seed_admin
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.security import verify_password
from app.modules.user.models import User, UserRole


@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


class TestSeedAdmin:
    def test_creates_admin_user(self, session):
        user = seed_admin(
            email="admin@example.com", password="supersecret", full_name="Admin", session=session
        )

        assert user.id is not None
        assert user.email == "admin@example.com"
        assert user.full_name == "Admin"
        assert user.role == UserRole.ADMIN
        assert user.is_active is True

        # `UserRead` (what `seed_admin` returns) never carries the password
        # hash by design — verify it against the persisted row instead.
        stored = session.get(User, user.id)
        assert verify_password("supersecret", stored.hashed_password)

    def test_same_email_twice_raises_without_duplicating(self, session):
        seed_admin(
            email="admin@example.com", password="supersecret", full_name="Admin", session=session
        )

        with pytest.raises(AdminAlreadyExistsError):
            seed_admin(
                email="admin@example.com",
                password="anotherpass",
                full_name="Admin 2",
                session=session,
            )

        users = session.exec(select(User).where(User.email == "admin@example.com")).all()
        assert len(users) == 1
        assert users[0].full_name == "Admin"  # untouched by the second, rejected call


class TestIsValidEmail:
    def test_accepts_valid_email(self):
        assert is_valid_email("admin@example.com") is True

    def test_rejects_invalid_email(self):
        assert is_valid_email("not-an-email") is False
