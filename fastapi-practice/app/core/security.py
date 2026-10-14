# Standard library
import uuid
from datetime import UTC, datetime, timedelta

# Third-party
import bcrypt
import jwt

# Local application
# core
from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError


def hash_password(plain: str) -> str:
    hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """True if `plain` matches `hashed`; False (never raises) on a malformed hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Encode a signed access token for `subject` (the user id, as a str).
    Defaults to `settings.access_token_expire_minutes`; `jti` is a fresh
    uuid4, the key `token_denylist.py` revokes logout by."""
    settings = get_settings()
    now = datetime.now(UTC)
    expire = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": now,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and verify `token`; raises `UnauthorizedError`, not a `jwt.*`
    exception, if expired or invalid."""
    settings = get_settings()

    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
