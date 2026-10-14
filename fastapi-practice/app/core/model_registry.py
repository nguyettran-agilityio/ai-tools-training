"""Imports every domain module's `models.py` so `SQLModel.metadata` knows
about all tables — imported by `alembic/env.py` (autogenerate needs every
table registered) and by tests that build their own throwaway in-memory
engine via `SQLModel.metadata.create_all(...)`."""

# Local application
# book
from app.modules.book.models import Book

# borrowing
from app.modules.borrowing.models import Borrowing

# category
from app.modules.category.models import Category

# reservation
from app.modules.reservation.models import Reservation

# user
from app.modules.user.models import User

__all__ = ["Book", "Borrowing", "Category", "Reservation", "User"]
