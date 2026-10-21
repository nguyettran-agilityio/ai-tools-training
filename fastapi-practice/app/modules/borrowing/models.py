# Standard library
import uuid
from datetime import UTC, datetime

# Third-party
from sqlmodel import Field, SQLModel


class Borrowing(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # `ondelete="CASCADE"` on both FKs for the same reason: `BookService.delete`
    # and `UserService.delete` already 409 while any *active* borrowing
    # references the book/user (see `BorrowingRepository.count_active_by_book`/
    # `count_active_by_user`), so a book or user only ever reaches the DELETE
    # statement with returned/historical borrowings still pointing at it;
    # those rows going with it is the intended behavior, not a DB-level FK
    # violation.
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    book_id: uuid.UUID = Field(foreign_key="book.id", ondelete="CASCADE", index=True)
    borrowed_at: datetime
    due_date: datetime
    returned_at: datetime | None = None
    # Set once by `BorrowingService.renew`; `None` means the loan was never
    # renewed, which is all the "renew at most once" rule needs.
    renewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
