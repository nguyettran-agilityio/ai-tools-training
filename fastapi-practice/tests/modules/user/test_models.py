"""User model round-trip and constraint tests, against an in-memory SQLite DB."""

import uuid
from collections.abc import Generator
from datetime import UTC

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, text

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.modules.user.models import User, UserRole


@pytest.fixture
def session(db_engine) -> Generator[Session, None, None]:
    with Session(db_engine) as session:
        yield session


def make_user(session: Session, **overrides) -> User:
    defaults = {
        "email": f"{uuid.uuid4()}@example.com",
        "hashed_password": "hashed",
        "full_name": "Jane Member",
    }
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class TestUserModel:
    def test_insert_and_round_trip(self, session):
        user = make_user(session, role=UserRole.ADMIN)

        fetched = session.get(User, user.id)
        assert fetched is not None
        assert isinstance(fetched.id, uuid.UUID)
        assert fetched.email == user.email
        assert fetched.role == UserRole.ADMIN
        assert fetched.role.value == "admin"
        assert fetched.is_active is True

    def test_default_role_is_member(self, session):
        user = make_user(session)
        assert user.role == UserRole.MEMBER

    def test_created_at_default_is_timezone_aware_utc(self):
        # Checked on the freshly-constructed object, before a DB round-trip:
        # SQLite has no native timezone-aware datetime type, so tzinfo is
        # stripped once a value has been stored and re-read — a storage
        # limitation, not a modeling bug.
        user = User(email="tz@example.com", hashed_password="x", full_name="Tz Check")
        assert user.created_at.tzinfo is not None
        assert user.created_at.tzinfo == UTC

    def test_duplicate_email_raises_integrity_error(self, session):
        make_user(session, email="dup@example.com")
        session.add(User(email="dup@example.com", hashed_password="x", full_name="Dup"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_admin_role_is_stored_as_lowercase_value(self, session):
        # Regression test: SQLAlchemy's auto-derived Enum column stores by
        # member NAME ("ADMIN") unless told otherwise — assert the RAW
        # column value via plain SQL, bypassing the ORM's enum decoding,
        # which would silently paper over a NAME-vs-VALUE mismatch.
        user = make_user(session, email="admin@example.com", role=UserRole.ADMIN)

        raw_role = session.exec(
            text("SELECT role FROM user WHERE email = :email").bindparams(email=user.email)
        ).one()[0]
        assert raw_role == "admin"

    def test_default_role_is_stored_as_lowercase_value(self, session):
        # sa_column bypasses Field(default=...) at the DB-schema level, so
        # this specifically guards that SQLModel/Pydantic's Python-side
        # default still lands in the DB as "member", not "MEMBER" or NULL.
        user = make_user(session, email="member@example.com")

        raw_role = session.exec(
            text("SELECT role FROM user WHERE email = :email").bindparams(email=user.email)
        ).one()[0]
        assert raw_role == "member"
