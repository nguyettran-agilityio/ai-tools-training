"""In-memory fakes implementing repository interfaces, for service-level
unit tests with no database, no session, no `TestClient`. Add one per
module as it migrates onto `CrudRepositoryInterface`.
"""

# Standard library
import uuid
from datetime import UTC, datetime
from typing import Any

# Local application
from app.modules.book.repositories import BookRepositoryInterface, BookUpdateFields
from app.modules.book.schemas import BookRead
from app.modules.borrowing.repositories import BorrowingRepositoryInterface, BorrowingUpdateFields
from app.modules.borrowing.schemas import BorrowingRead
from app.modules.category.repositories import CategoryRepositoryInterface, CategoryUpdateFields
from app.modules.category.schemas import CategoryRead
from app.modules.reservation.enums import ReservationStatus
from app.modules.reservation.repositories import (
    ReservationRepositoryInterface,
    ReservationUpdateFields,
)
from app.modules.reservation.schemas import ReservationRead
from app.modules.user.enums import UserRole
from app.modules.user.repositories import UserRepositoryInterface, UserUpdateFields
from app.modules.user.schemas import UserCredentials, UserRead


class FakeCategoryRepository(CategoryRepositoryInterface):
    """Backed by a plain dict — no session, no SQL, no file on disk."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, CategoryRead] = {}

    def get_by_id(self, id: uuid.UUID) -> CategoryRead | None:
        return self._rows.get(id)

    def get_by_name(self, name: str) -> CategoryRead | None:
        return next((row for row in self._rows.values() if row.name == name), None)

    def list(self, offset: int, limit: int) -> tuple[list[CategoryRead], int]:
        items = list(self._rows.values())
        return items[offset : offset + limit], len(items)

    def create(self, data: dict[str, Any]) -> CategoryRead:
        category = CategoryRead(
            id=uuid.uuid4(),
            name=data["name"],
            description=data.get("description"),
            created_at=datetime.now(UTC),
        )
        self._rows[category.id] = category
        return category

    def update(self, id: uuid.UUID, changes: CategoryUpdateFields) -> CategoryRead:
        updated = self._rows[id].model_copy(update=changes)
        self._rows[id] = updated
        return updated

    def delete(self, id: uuid.UUID) -> None:
        self._rows.pop(id, None)


class FakeUserRepository(UserRepositoryInterface):
    """Backed by a plain dict — no session, no SQL, no file on disk. Stores
    `hashed_password` internally (never on `UserRead`) so `get_credentials_by_email`
    can serve it without ever exposing it through the generic CRUD methods."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, UserRead] = {}
        self._hashed_passwords: dict[uuid.UUID, str] = {}

    def get_by_id(self, id: uuid.UUID) -> UserRead | None:
        return self._rows.get(id)

    def get_by_email(self, email: str) -> UserRead | None:
        return next((row for row in self._rows.values() if row.email == email), None)

    def get_credentials_by_email(self, email: str) -> UserCredentials | None:
        user = self.get_by_email(email)
        if user is None:
            return None
        return UserCredentials(
            id=user.id, hashed_password=self._hashed_passwords[user.id], is_active=user.is_active
        )

    def list_filtered(
        self, offset: int, limit: int, role: UserRole | None, is_active: bool | None
    ) -> tuple[list[UserRead], int]:
        items = [
            row
            for row in self._rows.values()
            if (role is None or row.role == role)
            and (is_active is None or row.is_active == is_active)
        ]
        return items[offset : offset + limit], len(items)

    def list(self, offset: int, limit: int) -> tuple[list[UserRead], int]:
        items = list(self._rows.values())
        return items[offset : offset + limit], len(items)

    def create(self, data: dict[str, Any]) -> UserRead:
        user = UserRead(
            id=uuid.uuid4(),
            email=data["email"],
            full_name=data["full_name"],
            role=data["role"],
            is_active=data["is_active"],
            created_at=datetime.now(UTC),
        )
        self._rows[user.id] = user
        self._hashed_passwords[user.id] = data["hashed_password"]
        return user

    def update(self, id: uuid.UUID, changes: UserUpdateFields) -> UserRead:
        updated = self._rows[id].model_copy(update=changes)
        self._rows[id] = updated
        return updated

    def delete(self, id: uuid.UUID) -> None:
        self._rows.pop(id, None)
        self._hashed_passwords.pop(id, None)


class FakeBookRepository(BookRepositoryInterface):
    """Backed by a plain dict — no session, no SQL, no file on disk."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, BookRead] = {}

    def get_by_id(self, id: uuid.UUID) -> BookRead | None:
        return self._rows.get(id)

    def get_by_isbn(self, isbn: str) -> BookRead | None:
        return next((row for row in self._rows.values() if row.isbn == isbn), None)

    def search(
        self,
        query: str | None,
        category_id: uuid.UUID | None,
        offset: int,
        limit: int,
        available_only: bool = False,
    ) -> tuple[list[BookRead], int]:
        items = [
            row
            for row in self._rows.values()
            if (category_id is None or row.category_id == category_id)
            and (not available_only or row.available_copies > 0)
        ]
        return items[offset : offset + limit], len(items)

    def count_by_category(self, category_id: uuid.UUID) -> int:
        return sum(1 for row in self._rows.values() if row.category_id == category_id)

    def list(self, offset: int, limit: int) -> tuple[list[BookRead], int]:
        items = list(self._rows.values())
        return items[offset : offset + limit], len(items)

    def create(self, data: dict[str, Any]) -> BookRead:
        book = BookRead(
            id=uuid.uuid4(),
            title=data["title"],
            author=data["author"],
            isbn=data["isbn"],
            description=data.get("description"),
            category_id=data["category_id"],
            total_copies=data["total_copies"],
            available_copies=data["available_copies"],
            created_at=datetime.now(UTC),
        )
        self._rows[book.id] = book
        return book

    def update(self, id: uuid.UUID, changes: BookUpdateFields) -> BookRead:
        updated = self._rows[id].model_copy(update=changes)
        self._rows[id] = updated
        return updated

    def delete(self, id: uuid.UUID) -> None:
        self._rows.pop(id, None)

    def try_decrement_available_copies(self, book_id: uuid.UUID) -> bool:
        book = self._rows[book_id]
        if book.available_copies <= 0:
            return False
        self._rows[book_id] = book.model_copy(
            update={"available_copies": book.available_copies - 1}
        )
        return True

    def increment_available_copies(self, book_id: uuid.UUID) -> None:
        book = self._rows[book_id]
        capped = min(book.available_copies + 1, book.total_copies)
        self._rows[book_id] = book.model_copy(update={"available_copies": capped})


class FakeBorrowingRepository(BorrowingRepositoryInterface):
    """Backed by a plain dict — no session, no SQL, no file on disk."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, BorrowingRead] = {}

    def get_by_id(self, id: uuid.UUID) -> BorrowingRead | None:
        return self._rows.get(id)

    def list_active_by_user(self, user_id: uuid.UUID) -> list[BorrowingRead]:
        return [
            row for row in self._rows.values() if row.user_id == user_id and row.returned_at is None
        ]

    def count_active_by_user(self, user_id: uuid.UUID) -> int:
        return len(self.list_active_by_user(user_id))

    def get_active_by_user_and_book(
        self, user_id: uuid.UUID, book_id: uuid.UUID
    ) -> BorrowingRead | None:
        return next(
            (
                row
                for row in self._rows.values()
                if row.user_id == user_id and row.book_id == book_id and row.returned_at is None
            ),
            None,
        )

    def list_by_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[BorrowingRead], int]:
        items = sorted(
            (row for row in self._rows.values() if row.user_id == user_id),
            key=lambda row: row.borrowed_at,
            reverse=True,
        )
        return items[offset : offset + limit], len(items)

    def list_all(
        self,
        offset: int,
        limit: int,
        overdue_only: bool = False,
        now: datetime | None = None,
    ) -> tuple[list[BorrowingRead], int]:
        reference_time = now or datetime.now(UTC)
        items = [
            row
            for row in self._rows.values()
            if not overdue_only or (row.returned_at is None and row.due_date < reference_time)
        ]
        items.sort(key=lambda row: row.borrowed_at, reverse=True)
        return items[offset : offset + limit], len(items)

    def count_active_by_book(self, book_id: uuid.UUID) -> int:
        return sum(
            1 for row in self._rows.values() if row.book_id == book_id and row.returned_at is None
        )

    def list(self, offset: int, limit: int) -> tuple[list[BorrowingRead], int]:
        items = list(self._rows.values())
        return items[offset : offset + limit], len(items)

    def create(self, data: dict[str, Any]) -> BorrowingRead:
        borrowing = BorrowingRead(
            id=uuid.uuid4(),
            user_id=data["user_id"],
            book_id=data["book_id"],
            borrowed_at=data["borrowed_at"],
            due_date=data["due_date"],
            returned_at=data.get("returned_at"),
            renewed_at=data.get("renewed_at"),
        )
        self._rows[borrowing.id] = borrowing
        return borrowing

    def update(self, id: uuid.UUID, changes: BorrowingUpdateFields) -> BorrowingRead:
        updated = self._rows[id].model_copy(update=changes)
        self._rows[id] = updated
        return updated

    def delete(self, id: uuid.UUID) -> None:
        self._rows.pop(id, None)

    def mark_returned(self, id: uuid.UUID, returned_at: datetime) -> BorrowingRead:
        return self.update(id, {"returned_at": returned_at})

    def mark_renewed(
        self, id: uuid.UUID, due_date: datetime, renewed_at: datetime
    ) -> BorrowingRead:
        return self.update(id, {"due_date": due_date, "renewed_at": renewed_at})


class FakeReservationRepository(ReservationRepositoryInterface):
    """Backed by a plain dict — no session, no SQL, no file on disk."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, ReservationRead] = {}

    def get_by_id(self, id: uuid.UUID) -> ReservationRead | None:
        return self._rows.get(id)

    def list_pending_for_book(self, book_id: uuid.UUID) -> list[ReservationRead]:
        items = [
            row
            for row in self._rows.values()
            if row.book_id == book_id
            and row.status in (ReservationStatus.PENDING, ReservationStatus.NOTIFIED)
        ]
        return sorted(items, key=lambda row: row.created_at)

    def get_open_by_user_and_book(
        self, user_id: uuid.UUID, book_id: uuid.UUID
    ) -> ReservationRead | None:
        return next(
            (
                row
                for row in self._rows.values()
                if row.user_id == user_id
                and row.book_id == book_id
                and row.status in (ReservationStatus.PENDING, ReservationStatus.NOTIFIED)
            ),
            None,
        )

    def list_by_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[ReservationRead], int]:
        items = sorted(
            (row for row in self._rows.values() if row.user_id == user_id),
            key=lambda row: row.created_at,
            reverse=True,
        )
        return items[offset : offset + limit], len(items)

    def list(self, offset: int, limit: int) -> tuple[list[ReservationRead], int]:
        items = list(self._rows.values())
        return items[offset : offset + limit], len(items)

    def count_open_by_book(self, book_id: uuid.UUID) -> int:
        return sum(
            1
            for row in self._rows.values()
            if row.book_id == book_id
            and row.status in (ReservationStatus.PENDING, ReservationStatus.NOTIFIED)
        )

    def count_open_by_book_excluding_user(self, book_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return sum(
            1
            for row in self._rows.values()
            if row.book_id == book_id
            and row.user_id != user_id
            and row.status in (ReservationStatus.PENDING, ReservationStatus.NOTIFIED)
        )

    def count_open_by_user(self, user_id: uuid.UUID) -> int:
        return sum(
            1
            for row in self._rows.values()
            if row.user_id == user_id
            and row.status in (ReservationStatus.PENDING, ReservationStatus.NOTIFIED)
        )

    def create(self, data: dict[str, Any]) -> ReservationRead:
        reservation = ReservationRead(
            id=uuid.uuid4(),
            user_id=data["user_id"],
            book_id=data["book_id"],
            status=ReservationStatus.PENDING,
            created_at=datetime.now(UTC),
            notified_at=None,
        )
        self._rows[reservation.id] = reservation
        return reservation

    def update(self, id: uuid.UUID, changes: ReservationUpdateFields) -> ReservationRead:
        updated = self._rows[id].model_copy(update=changes)
        self._rows[id] = updated
        return updated

    def delete(self, id: uuid.UUID) -> None:
        self._rows.pop(id, None)

    def mark_cancelled(self, id: uuid.UUID) -> ReservationRead:
        return self.update(id, {"status": ReservationStatus.CANCELLED})

    def mark_notified(self, id: uuid.UUID, notified_at: datetime) -> ReservationRead:
        return self.update(id, {"status": ReservationStatus.NOTIFIED, "notified_at": notified_at})

    def mark_fulfilled(self, id: uuid.UUID) -> ReservationRead:
        return self.update(id, {"status": ReservationStatus.FULFILLED})
