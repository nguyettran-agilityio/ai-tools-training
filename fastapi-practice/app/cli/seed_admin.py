"""Create the first admin user.

Usage:
    uv run python -m app.cli.seed_admin
    uv run python -m app.cli.seed_admin --email admin@gmail.com --full-name "Admin"

Credentials resolve per-field: CLI arg > env var (ADMIN_EMAIL / ADMIN_PASSWORD /
ADMIN_FULL_NAME) > interactive prompt. Idempotent-safe: exits 1 if the email
already exists, without modifying anything.
"""

# Standard library
import argparse
import getpass
import os
import sys

# Third-party
from pydantic import BaseModel, EmailStr, ValidationError
from sqlmodel import Session

# Local application
# core
from app.core.db import session_scope
from app.core.repository_sqlmodel import SQLModelBackend
from app.core.security import hash_password

# user
from app.modules.user.mappers import to_user_read
from app.modules.user.models import User, UserRole
from app.modules.user.repositories_sqlmodel import UserRepository
from app.modules.user.schemas import UserRead

MIN_PASSWORD_LENGTH = 8


class AdminAlreadyExistsError(Exception):
    """Raised by `seed_admin` when a user with the given email already exists."""

    def __init__(self, email: str) -> None:
        self.email = email
        super().__init__(f"A user with email {email!r} already exists")


class _EmailCheck(BaseModel):
    # Tiny inline model reusing pydantic's EmailStr, rather than pulling in
    # a standalone email-validation dependency just for this one check.
    email: EmailStr


def is_valid_email(email: str) -> bool:
    try:
        _EmailCheck(email=email)
    except ValidationError:
        return False
    return True


def seed_admin(email: str, password: str, full_name: str, session: Session) -> UserRead:
    """Core logic, isolated from argparse/env/prompts so it's directly
    testable. Never commits — the caller's `session_scope()` owns that."""
    repo = UserRepository(SQLModelBackend(session, User, to_user_read))
    if repo.get_by_email(email) is not None:
        raise AdminAlreadyExistsError(email)

    return repo.create(
        {
            "email": email,
            "hashed_password": hash_password(password),
            "full_name": full_name,
            "role": UserRole.ADMIN,
            "is_active": True,
        }
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Admin email (falls back to ADMIN_EMAIL, then a prompt)")
    parser.add_argument(
        "--password", help="Admin password (falls back to ADMIN_PASSWORD, then a prompt)"
    )
    parser.add_argument(
        "--full-name",
        dest="full_name",
        help="Admin full name (falls back to ADMIN_FULL_NAME, then a prompt)",
    )
    return parser.parse_args()


def _resolve_email(args: argparse.Namespace) -> str:
    email = args.email or os.environ.get("ADMIN_EMAIL")
    while not email or not is_valid_email(email):
        if email:
            print(f"'{email}' is not a valid email address, try again.")
        email = input("Admin email: ").strip()
    return email


def _resolve_full_name(args: argparse.Namespace) -> str:
    full_name = args.full_name or os.environ.get("ADMIN_FULL_NAME")
    while not full_name:
        full_name = input("Admin full name: ").strip()
    return full_name


def _resolve_password(args: argparse.Namespace) -> str:
    env_password = os.environ.get("ADMIN_PASSWORD")
    password = args.password or env_password
    if password:
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
            sys.exit(1)
        return password

    for _ in range(3):
        first = getpass.getpass("Admin password: ")
        if len(first) < MIN_PASSWORD_LENGTH:
            print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters, try again.")
            continue
        second = getpass.getpass("Confirm password: ")
        if first != second:
            print("Passwords did not match, try again.")
            continue
        return first

    print("Too many failed attempts.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    args = _parse_args()
    email = _resolve_email(args)
    full_name = _resolve_full_name(args)
    password = _resolve_password(args)

    try:
        with session_scope() as session:
            user = seed_admin(email=email, password=password, full_name=full_name, session=session)
            created_id, created_email = user.id, user.email
    except AdminAlreadyExistsError:
        print(f"A user with email {email!r} already exists — nothing to do.", file=sys.stderr)
        sys.exit(1)

    print(f"Admin user created: email={created_email} id={created_id}")


if __name__ == "__main__":
    main()
