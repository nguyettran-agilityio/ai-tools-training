"""UserRepository tests, against an in-memory SQLite DB.

Custom queries beyond the inherited CRUD: `get_by_email`,
`get_credentials_by_email` (the one path `hashed_password` leaves the
repository through), and `list_filtered` (role/is_active filters).
"""

import uuid
from collections.abc import Generator

import pytest
from sqlmodel import Session

from app.core import db as _db  # noqa: F401  (registers the SQLite FK-pragma listener)
from app.core import model_registry  # noqa: F401  (registers all tables on metadata)
from app.core.repository_sqlmodel import SQLModelBackend
from app.modules.user.mappers import to_user_read
from app.modules.user.models import User, UserRole
from app.modules.user.repositories_sqlmodel import UserRepository


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
    session.flush()
    session.refresh(user)
    return user


class TestUserRepositoryCrud:
    def _make_repo(self, session: Session) -> UserRepository:
        return UserRepository(SQLModelBackend(session, User, to_user_read))

    def test_get_by_email(self, session):
        repo = self._make_repo(session)
        make_user(session, email="jane@example.com")

        assert repo.get_by_email("jane@example.com") is not None
        assert repo.get_by_email("nobody@example.com") is None

    def test_get_credentials_by_email_carries_the_hash_but_get_by_email_does_not(self, session):
        repo = self._make_repo(session)
        make_user(session, email="jane@example.com", hashed_password="a-real-hash")

        credentials = repo.get_credentials_by_email("jane@example.com")
        assert credentials.hashed_password == "a-real-hash"
        assert not hasattr(repo.get_by_email("jane@example.com"), "hashed_password")

    def test_list_filtered_combines_role_and_is_active(self, session):
        repo = self._make_repo(session)
        make_user(session, email="m1@example.com", role=UserRole.MEMBER, is_active=True)
        make_user(session, email="m2@example.com", role=UserRole.MEMBER, is_active=False)
        make_user(session, email="a1@example.com", role=UserRole.ADMIN, is_active=True)

        items, total = repo.list_filtered(0, 10, role=UserRole.MEMBER, is_active=None)
        assert total == 2

        items, total = repo.list_filtered(0, 10, role=None, is_active=False)
        assert total == 1
        assert items[0].email == "m2@example.com"

        items, total = repo.list_filtered(0, 10, role=UserRole.MEMBER, is_active=True)
        assert total == 1
        assert items[0].email == "m1@example.com"
