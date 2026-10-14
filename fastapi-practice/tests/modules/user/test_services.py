"""Unit tests for `AuthService`/`UserService` against `FakeUserRepository` —
no database, no session, no `TestClient`. Compare with `tests/test_auth.py`/
`tests/test_users.py` (same behavior, through the real HTTP API + DB).
"""

# Standard library
import uuid
from unittest.mock import create_autospec

# Third-party
import pytest

# Local application
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, UnauthorizedError
from app.core.schemas import PaginationParams
from app.core.security import decode_access_token
from app.core.token_denylist import InMemoryTokenDenylist
from app.modules.borrowing.repositories import BorrowingRepositoryInterface
from app.modules.reservation.repositories import ReservationRepositoryInterface
from app.modules.user.enums import UserRole
from app.modules.user.schemas import LoginRequest, UserCreate, UserUpdate
from app.modules.user.services import AuthService, UserService
from tests.fakes import FakeUserRepository


@pytest.fixture
def user_repository():
    return FakeUserRepository()


@pytest.fixture
def borrowing_repository():
    repository = create_autospec(BorrowingRepositoryInterface, instance=True)
    repository.count_active_by_user.return_value = 0
    return repository


@pytest.fixture
def reservation_repository():
    repository = create_autospec(ReservationRepositoryInterface, instance=True)
    repository.count_open_by_user.return_value = 0
    return repository


@pytest.fixture
def auth_service(user_repository):
    return AuthService(user_repository, InMemoryTokenDenylist())


@pytest.fixture
def user_service(user_repository, borrowing_repository, reservation_repository):
    return UserService(user_repository, borrowing_repository, reservation_repository)


class TestRegister:
    def test_creates_a_member_and_returns_a_dto(self, auth_service):
        result = auth_service.register(
            UserCreate(email="jane@example.com", password="supersecret", full_name="Jane Doe")
        )

        assert result.id is not None
        assert result.role == UserRole.MEMBER
        assert not hasattr(result, "hashed_password")

    def test_duplicate_email_raises_conflict(self, auth_service):
        data = UserCreate(email="jane@example.com", password="supersecret", full_name="Jane Doe")
        auth_service.register(data)

        with pytest.raises(ConflictError):
            auth_service.register(data)


class TestLogin:
    def test_correct_credentials_returns_token_for_that_user(self, auth_service):
        registered = auth_service.register(
            UserCreate(email="jane@example.com", password="supersecret", full_name="Jane Doe")
        )

        token = auth_service.login(LoginRequest(email="jane@example.com", password="supersecret"))

        assert decode_access_token(token)["sub"] == str(registered.id)

    def test_wrong_password_raises_unauthorized(self, auth_service):
        auth_service.register(
            UserCreate(email="jane@example.com", password="supersecret", full_name="Jane Doe")
        )

        with pytest.raises(UnauthorizedError):
            auth_service.login(LoginRequest(email="jane@example.com", password="wrong"))

    def test_unknown_email_raises_unauthorized_with_same_message(self, auth_service):
        with pytest.raises(UnauthorizedError, match="Invalid email or password"):
            auth_service.login(LoginRequest(email="nobody@example.com", password="x"))

    def test_inactive_user_raises_unauthorized(self, auth_service, user_repository):
        registered = auth_service.register(
            UserCreate(email="jane@example.com", password="supersecret", full_name="Jane Doe")
        )
        user_repository.update(registered.id, {"is_active": False})

        with pytest.raises(UnauthorizedError):
            auth_service.login(LoginRequest(email="jane@example.com", password="supersecret"))


class TestLogout:
    def test_denylists_the_tokens_jti_until_it_would_have_expired(self, auth_service):
        token = _register_and_login(auth_service, "jane@example.com", "supersecret")
        payload = decode_access_token(token)

        auth_service.logout(payload)

        assert auth_service.denylist.is_denied(payload["jti"]) is True


def _register_and_login(auth_service: AuthService, email: str, password: str) -> str:
    auth_service.register(UserCreate(email=email, password=password, full_name="Jane Doe"))
    return auth_service.login(LoginRequest(email=email, password=password))


class TestList:
    def test_filters_by_role_and_is_active(self, user_service):
        user_service.create(_new_user("member1@example.com"), role=UserRole.MEMBER)
        user_service.create(_new_user("member2@example.com"), role=UserRole.MEMBER)
        admin = user_service.create(_new_user("admin@example.com"), role=UserRole.ADMIN)
        user_service.update(admin.id, UserUpdate(is_active=False), acting_user_id=uuid.uuid4())

        page = user_service.list(UserRole.MEMBER, None, PaginationParams(page=1, page_size=10))
        assert page.total == 2

        page = user_service.list(None, False, PaginationParams(page=1, page_size=10))
        assert page.total == 1
        assert page.items[0].email == "admin@example.com"


class TestCreate:
    def test_creates_with_caller_chosen_role(self, user_service):
        result = user_service.create(_new_user("admin@example.com"), role=UserRole.ADMIN)
        assert result.role == UserRole.ADMIN


class TestUpdate:
    def test_partial_update_keeps_untouched_fields(self, user_service):
        created = user_service.create(_new_user("jane@example.com"))

        updated = user_service.update(
            created.id, UserUpdate(full_name="Jane Updated"), acting_user_id=uuid.uuid4()
        )

        assert updated.full_name == "Jane Updated"
        assert updated.email == "jane@example.com"

    def test_missing_user_raises_not_found(self, user_service):
        with pytest.raises(NotFoundError):
            user_service.update(
                uuid.uuid4(), UserUpdate(full_name="X"), acting_user_id=uuid.uuid4()
            )

    def test_admin_cannot_deactivate_own_account(self, user_service):
        created = user_service.create(_new_user("admin@example.com"), role=UserRole.ADMIN)

        with pytest.raises(BadRequestError):
            user_service.update(created.id, UserUpdate(is_active=False), acting_user_id=created.id)

    def test_admin_cannot_demote_own_account(self, user_service):
        created = user_service.create(_new_user("admin@example.com"), role=UserRole.ADMIN)

        with pytest.raises(BadRequestError):
            user_service.update(
                created.id, UserUpdate(role=UserRole.MEMBER), acting_user_id=created.id
            )


class TestDelete:
    def test_deletes_when_no_active_borrowings(self, user_service, user_repository):
        created = user_service.create(_new_user("jane@example.com"))

        user_service.delete(created.id, acting_user_id=uuid.uuid4())

        assert user_repository.get_by_id(created.id) is None

    def test_refuses_when_active_borrowings_exist(self, user_service, borrowing_repository):
        created = user_service.create(_new_user("jane@example.com"))
        borrowing_repository.count_active_by_user.return_value = 2

        with pytest.raises(ConflictError):
            user_service.delete(created.id, acting_user_id=uuid.uuid4())

    def test_refuses_when_open_reservations_exist(self, user_service, reservation_repository):
        created = user_service.create(_new_user("jane@example.com"))
        reservation_repository.count_open_by_user.return_value = 1

        with pytest.raises(ConflictError):
            user_service.delete(created.id, acting_user_id=uuid.uuid4())

    def test_refuses_self_delete(self, user_service):
        created = user_service.create(_new_user("jane@example.com"))

        with pytest.raises(BadRequestError):
            user_service.delete(created.id, acting_user_id=created.id)

    def test_missing_user_raises_not_found(self, user_service):
        with pytest.raises(NotFoundError):
            user_service.delete(uuid.uuid4(), acting_user_id=uuid.uuid4())


def _new_user(email: str) -> UserCreate:
    return UserCreate(email=email, password="supersecret", full_name="Jane Doe")
