"""Seed a small, fixed demo dataset for live demos.

Usage:
    uv run python -m app.cli.seed_demo
    uv run python -m app.cli.seed_demo --force

Separate from `seed_admin.py` — touches only rows matched by the fixed
identifiers defined below, never a broad query. Seeds 1 admin + 4 members,
3 categories, 6 fully-available "clean" books, and 2 books with pre-created
overdue borrowings for Alice.

Idempotent-safe: no-op if `admin@example.com` exists and `--force` isn't
passed. `--force` deletes every previously-seeded row and reseeds from
scratch, but never deletes the demo admin itself.
"""

# Standard library
import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# Third-party
from sqlmodel import Session, or_, select

# Local application
# core
from app.core.db import session_scope
from app.core.repository_sqlmodel import SQLModelBackend
from app.core.security import hash_password

# book
from app.modules.book.mappers import to_book_read
from app.modules.book.models import Book
from app.modules.book.repositories_sqlmodel import BookRepository
from app.modules.book.schemas import BookRead

# borrowing
from app.modules.borrowing.mappers import to_borrowing_read
from app.modules.borrowing.models import Borrowing
from app.modules.borrowing.repositories_sqlmodel import BorrowingRepository
from app.modules.borrowing.schemas import BorrowingRead

# category
from app.modules.category.mappers import to_category_read
from app.modules.category.models import Category
from app.modules.category.repositories_sqlmodel import CategoryRepository
from app.modules.category.schemas import CategoryRead

# reservation
from app.modules.reservation.models import Reservation

# user
from app.modules.user.mappers import to_user_read
from app.modules.user.models import User, UserRole
from app.modules.user.repositories_sqlmodel import UserRepository
from app.modules.user.schemas import UserRead

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Admin@123"
ADMIN_FULL_NAME = "Admin"

MEMBER_PASSWORD = "Member@123"
# (email, full_name) — index 0 (Alice) is the one used for the overdue
# borrowings. `example.com` (not `demo.com`/`gmail.com`) is the RFC 2606
# domain reserved for docs/demo/test use, so it can never collide with a
# real address. Emails stay fixed/predictable (they're the login
# credentials printed by the cheat sheet, and the identifiers
# `_delete_demo_data` matches on).
MEMBERS: list[tuple[str, str]] = [
    ("alice@example.com", "Alice"),
    ("bob@example.com", "Bob"),
    ("carol@example.com", "Carol"),
    ("david@example.com", "David"),
]

# (name, description)
CATEGORIES: list[tuple[str, str]] = [
    ("Programming", "Software engineering, languages, and design practices."),
    ("Science", "Popular science and scientific reference."),
    ("Fiction", "Novels and short fiction."),
]

# (title, author, isbn, category_name) — total_copies = available_copies = 1,
# so the demoer can freely borrow these live with no stale state, AND
# reservation is one borrow away to trigger: a second member's borrow
# attempt immediately falls through to the reservation queue (see
# `BorrowingService.borrow`) instead of needing several borrows first to
# exhaust a higher copy count.
CLEAN_BOOKS: list[tuple[str, str, str, str]] = [
    ("Clean Code", "Robert C. Martin", "9780132350884", "Programming"),
    ("The Pragmatic Programmer", "David Thomas", "9780135957059", "Programming"),
    ("A Brief History of Time", "Stephen Hawking", "9780553380163", "Science"),
    ("Cosmos", "Carl Sagan", "9780345539434", "Science"),
    ("Dune", "Frank Herbert", "9780441013593", "Fiction"),
    ("The Hobbit", "J.R.R. Tolkien", "9780547928227", "Fiction"),
]

# (title, author, isbn, category_name) — total_copies = 1, available_copies = 0;
# each gets exactly one pre-created, permanently-overdue borrowing for
# Alice (see `seed_demo`). Plain titles — these are already distinguishable
# from the clean, safe-to-borrow-live books above by `available_copies == 0`
# and by living in `result.overdue_books`, not `result.clean_books`.
OVERDUE_BOOKS: list[tuple[str, str, str, str]] = [
    ("Design Patterns", "Erich Gamma", "9780201633610", "Programming"),
    ("Sapiens", "Yuval Noah Harari", "9780062316097", "Science"),
]


@dataclass
class SeedDemoResult:
    admin: UserRead
    members: list[UserRead]
    categories: list[CategoryRead]
    clean_books: list[BookRead]
    overdue_books: list[BookRead]
    overdue_borrowings: list[BorrowingRead]


def _delete_demo_data(session: Session) -> None:
    """Remove every previously-seeded demo row, matched only by the fixed
    identifiers this script seeds. Reservations/borrowings are deleted first
    since neither has `ON DELETE CASCADE`."""
    user_repo = UserRepository(SQLModelBackend(session, User, to_user_read))
    category_repo = CategoryRepository(SQLModelBackend(session, Category, to_category_read))
    book_repo = BookRepository(SQLModelBackend(session, Book, to_book_read))

    member_ids = []
    for email, _ in MEMBERS:
        member = user_repo.get_by_email(email)
        if member is not None:
            member_ids.append(member.id)

    all_books = CLEAN_BOOKS + OVERDUE_BOOKS
    book_ids = []
    for _, _, isbn, _ in all_books:
        book = book_repo.get_by_isbn(isbn)
        if book is not None:
            book_ids.append(book.id)

    if book_ids or member_ids:
        reservations = session.exec(
            select(Reservation).where(
                or_(
                    Reservation.book_id.in_(book_ids),
                    Reservation.user_id.in_(member_ids),
                )
            )
        ).all()
        for reservation in reservations:
            session.delete(reservation)

        borrowings = session.exec(
            select(Borrowing).where(
                or_(Borrowing.book_id.in_(book_ids), Borrowing.user_id.in_(member_ids))
            )
        ).all()
        for borrowing in borrowings:
            session.delete(borrowing)

        session.flush()

    for _, _, isbn, _ in all_books:
        book = book_repo.get_by_isbn(isbn)
        if book is not None:
            book_repo.delete(book.id)

    for name, _ in CATEGORIES:
        category = category_repo.get_by_name(name)
        if category is not None:
            category_repo.delete(category.id)

    for email, _ in MEMBERS:
        member = user_repo.get_by_email(email)
        if member is not None:
            user_repo.delete(member.id)


def seed_demo(session: Session, force: bool = False) -> SeedDemoResult | None:
    """(Re)create the fixed demo dataset. Returns `None` (no changes) if
    `admin@example.com` exists and `force` is False."""
    user_repo = UserRepository(SQLModelBackend(session, User, to_user_read))
    category_repo = CategoryRepository(SQLModelBackend(session, Category, to_category_read))
    book_repo = BookRepository(SQLModelBackend(session, Book, to_book_read))
    borrowing_repo = BorrowingRepository(SQLModelBackend(session, Borrowing, to_borrowing_read))

    admin = user_repo.get_by_email(ADMIN_EMAIL)
    if admin is not None and not force:
        return None

    if force:
        _delete_demo_data(session)
        admin = user_repo.get_by_email(ADMIN_EMAIL)

    if admin is None:
        admin = user_repo.create(
            {
                "email": ADMIN_EMAIL,
                "hashed_password": hash_password(ADMIN_PASSWORD),
                "full_name": ADMIN_FULL_NAME,
                "role": UserRole.ADMIN,
                "is_active": True,
            }
        )

    members = [
        user_repo.create(
            {
                "email": email,
                "hashed_password": hash_password(MEMBER_PASSWORD),
                "full_name": full_name,
                "role": UserRole.MEMBER,
                "is_active": True,
            }
        )
        for email, full_name in MEMBERS
    ]

    categories = [
        category_repo.create({"name": name, "description": description})
        for name, description in CATEGORIES
    ]
    category_by_name = {category.name: category for category in categories}

    clean_books = [
        book_repo.create(
            {
                "title": title,
                "author": author,
                "isbn": isbn,
                "category_id": category_by_name[category_name].id,
                "total_copies": 1,
                "available_copies": 1,
            }
        )
        for title, author, isbn, category_name in CLEAN_BOOKS
    ]

    overdue_books = [
        book_repo.create(
            {
                "title": title,
                "author": author,
                "isbn": isbn,
                "category_id": category_by_name[category_name].id,
                "total_copies": 1,
                "available_copies": 0,
            }
        )
        for title, author, isbn, category_name in OVERDUE_BOOKS
    ]

    # ~30 days ago, due ~16 days ago (30 - 14-day loan duration) — well past
    # due, so `due_date < now` holds regardless of exactly when this runs.
    now = datetime.now(UTC)
    borrowed_at = now - timedelta(days=30)
    due_date = now - timedelta(days=16)
    overdue_borrowings = [
        borrowing_repo.create(
            {
                "user_id": members[0].id,
                "book_id": book.id,
                "borrowed_at": borrowed_at,
                "due_date": due_date,
                "returned_at": None,
            }
        )
        for book in overdue_books
    ]

    return SeedDemoResult(
        admin=admin,
        members=members,
        categories=categories,
        clean_books=clean_books,
        overdue_books=overdue_books,
        overdue_borrowings=overdue_borrowings,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete any existing demo data first, then reseed from scratch.",
    )
    return parser.parse_args()


def _print_cheat_sheet(result: SeedDemoResult) -> None:
    print("Demo data ready.\n")

    print("Logins:")
    print(f"  admin    {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    for email, _ in MEMBERS:
        print(f"  member   {email} / {MEMBER_PASSWORD}")

    print("\nBooks available to borrow/reserve live (1 copy each):")
    for title, *_rest in CLEAN_BOOKS:
        print(f"  - {title}")
    print(
        "  (a second member's borrow on the same title falls straight into "
        "the reservation queue — no need to exhaust several copies first)"
    )

    print(
        f"\nNote: {MEMBERS[0][0]} already has 2 overdue borrowings "
        "(visible via GET /borrowings/overdue as admin)."
    )


def main() -> None:
    args = _parse_args()

    with session_scope() as session:
        result = seed_demo(session, force=args.force)

    if result is None:
        print(
            f"Demo data already exists ({ADMIN_EMAIL} found) — nothing to do. "
            "Pass --force to reseed.",
            file=sys.stderr,
        )
        sys.exit(1)

    _print_cheat_sheet(result)


if __name__ == "__main__":
    main()
