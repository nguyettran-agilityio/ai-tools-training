"""User Pydantic DTOs (request/response schemas)."""

# Standard library
import uuid
from datetime import datetime

# Third-party
from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Local application
# core
from app.core.schemas import CamelModel

# user
from app.modules.user.enums import UserRole


class UserCreate(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str


class AdminUserCreate(UserCreate):
    # Only exposed on the admin-only `POST /users` endpoint — `POST
    # /auth/register` always creates a member (see `AuthService.register`)
    # and never accepts a role from the client.
    role: UserRole = UserRole.MEMBER


class UserUpdate(CamelModel):
    full_name: str | None = None
    is_active: bool | None = None
    role: UserRole | None = None
    # email/password are not updatable through this schema — they need
    # their own dedicated (and separately validated) flows.


class UserRead(CamelModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    # hashed_password is intentionally never a field here — it must never
    # leave the service layer in a response.


class UserCredentials(BaseModel):
    """Internal-only DTO carrying `hashed_password`, for `AuthService.login`
    alone — never returned by any router."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hashed_password: str
    is_active: bool


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    # OAuth2's token response body is specified (RFC 6749 §5.1) as literal
    # snake_case JSON keys (access_token, token_type) — camelCase would
    # break OAuth2-compliant clients, so this schema opts out of CamelModel
    # and its alias_generator entirely.
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "bearer"
