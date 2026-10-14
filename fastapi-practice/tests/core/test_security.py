"""Password hashing tests for app/core/security.py."""

from app.core.security import hash_password, verify_password


def test_verify_password_accepts_correct_password():
    hashed = hash_password("supersecret")
    assert verify_password("supersecret", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("supersecret")
    assert verify_password("wrongpassword", hashed) is False


def test_hash_password_is_salted_not_deterministic():
    first = hash_password("supersecret")
    second = hash_password("supersecret")
    assert first != second
    # ...but both still verify against the same plaintext.
    assert verify_password("supersecret", first) is True
    assert verify_password("supersecret", second) is True


def test_verify_password_returns_false_on_malformed_hash():
    assert verify_password("supersecret", "not-a-real-bcrypt-hash") is False
    assert verify_password("supersecret", "") is False
