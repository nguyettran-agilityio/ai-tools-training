"""User role enum — plain Python, zero ORM imports, so non-ORM layers
(schemas, services, routers) can depend on it without pulling in SQLModel.
"""

# Standard library
from enum import StrEnum


class UserRole(StrEnum):
    """Stored roles. Anonymous access is not backed by a User row."""

    MEMBER = "member"
    ADMIN = "admin"
