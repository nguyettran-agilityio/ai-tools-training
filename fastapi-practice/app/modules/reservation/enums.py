"""Reservation status enum — plain Python, zero ORM imports, so non-ORM
layers (schemas, services, repositories) can depend on it without pulling
in SQLModel.
"""

# Standard library
from enum import StrEnum


class ReservationStatus(StrEnum):
    PENDING = "pending"
    NOTIFIED = "notified"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
