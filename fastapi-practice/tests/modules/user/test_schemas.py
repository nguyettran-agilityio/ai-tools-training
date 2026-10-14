"""User schema shape/validation tests. No DB involved (`from_attributes`
against a plain, unsaved `User` instance is enough for `UserRead`)."""

import pytest
from pydantic import ValidationError

from app.modules.user.enums import UserRole
from app.modules.user.models import User
from app.modules.user.schemas import UserCreate, UserRead


class TestUserRead:
    def test_model_validate_from_sqlmodel_instance(self):
        user = User(
            email="member@example.com",
            hashed_password="super-secret-hash",
            full_name="Jane Member",
            role=UserRole.MEMBER,
        )

        read = UserRead.model_validate(user)
        dumped = read.model_dump(by_alias=True)

        assert dumped["fullName"] == "Jane Member"
        assert dumped["isActive"] is True
        assert "createdAt" in dumped
        assert "hashedPassword" not in dumped
        assert "hashed_password" not in dumped

    def test_read_schema_has_no_hashed_password_field(self):
        assert "hashed_password" not in UserRead.model_fields


class TestUserCreate:
    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            UserCreate(email="not-an-email", password="longenough", full_name="Jane")

    def test_rejects_short_password(self):
        with pytest.raises(ValidationError):
            UserCreate(email="jane@example.com", password="short", full_name="Jane")

    def test_accepts_valid_input(self):
        user = UserCreate(email="jane@example.com", password="longenough", full_name="Jane")
        assert user.email == "jane@example.com"
