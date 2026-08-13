"""Password hashing and JWT issuing/verification.

Two changes from the previous implementation worth knowing:

* **argon2 instead of bcrypt.** argon2id is the current password-hashing
  recommendation and has no 72-byte input truncation. ``verify_password``
  transparently accepts existing bcrypt hashes so migrated accounts keep
  working, and reports when a hash should be upgraded on next login.
* **Access + refresh tokens.** Access tokens are short-lived (30 min) so a
  leaked one expires quickly; the long-lived refresh token is the only thing
  that can mint new ones, and it carries a token type claim so an access
  token can never be replayed as a refresh token.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jwt import InvalidTokenError

from .config import get_settings

settings = get_settings()

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify against an argon2 hash, falling back to bcrypt for legacy rows."""
    try:
        _hasher.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        # Not an argon2 hash -- this is a pre-migration bcrypt row.
        return _verify_legacy_bcrypt(plain_password, hashed_password)


def _verify_legacy_bcrypt(plain_password: str, hashed_password: str) -> bool:
    try:
        import bcrypt
    except ImportError:  # pragma: no cover - bcrypt is only needed for legacy rows
        return False
    try:
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    except ValueError:
        return False


def needs_rehash(hashed_password: str) -> bool:
    """True when the stored hash is bcrypt, or argon2 with outdated parameters.

    Callers should re-hash and persist on the next successful login, which is
    the only moment the plaintext is available.
    """
    try:
        return _hasher.check_needs_rehash(hashed_password)
    except InvalidHashError:
        return True  # legacy bcrypt


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------


def _create_token(subject: str, token_type: TokenType, expires_in: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_in,
        "jti": str(uuid4()),  # lets a specific token be revoked later
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(username: str) -> str:
    return _create_token(
        username, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(username: str) -> str:
    return _create_token(
        username, "refresh", timedelta(days=settings.refresh_token_expire_days)
    )


class TokenError(Exception):
    """Raised for any invalid, expired, or wrong-type token."""


def decode_token(token: str, expected_type: TokenType) -> str:
    """Return the subject of a valid token of ``expected_type``.

    Raises ``TokenError`` for expired, malformed, or wrong-type tokens. The
    type check is what stops a caller from presenting a long-lived refresh
    token as an access token (or vice versa).
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except InvalidTokenError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise TokenError("token has no subject")
    return subject
