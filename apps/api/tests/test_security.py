"""Password hashing and token handling.

These are the parts where a subtle bug is a security hole rather than a
visible failure, so they get direct tests.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)

settings = get_settings()


class TestPasswords:
    def test_roundtrip(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed)
        assert not verify_password("wrong", hashed)

    def test_hash_is_salted(self) -> None:
        """Two hashes of the same password must differ, or identical passwords
        are identifiable from the database alone."""
        assert hash_password("same") != hash_password("same")

    def test_uses_argon2(self) -> None:
        assert hash_password("x").startswith("$argon2")

    def test_accepts_legacy_bcrypt(self) -> None:
        """Migrated accounts must keep working after the argon2 switch."""
        bcrypt = pytest.importorskip("bcrypt")
        legacy = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode()

        assert verify_password("legacy-password", legacy)
        assert not verify_password("wrong", legacy)
        # ...and be flagged for upgrade on next login.
        assert needs_rehash(legacy)

    def test_argon2_hash_does_not_need_rehash(self) -> None:
        assert not needs_rehash(hash_password("x"))

    def test_long_password_is_not_truncated(self) -> None:
        """bcrypt silently truncates at 72 bytes, so two long passwords sharing
        a 72-byte prefix would verify against each other. argon2 does not."""
        base = "a" * 72
        hashed = hash_password(base + "ONE")
        assert not verify_password(base + "TWO", hashed)


class TestTokens:
    def test_access_token_roundtrip(self) -> None:
        assert decode_token(create_access_token("alice"), "access") == "alice"

    def test_refresh_token_roundtrip(self) -> None:
        assert decode_token(create_refresh_token("alice"), "refresh") == "alice"

    def test_access_token_rejected_as_refresh(self) -> None:
        """The whole point of the type claim: a short-lived access token must
        not be usable to mint new tokens indefinitely."""
        with pytest.raises(TokenError):
            decode_token(create_access_token("alice"), "refresh")

    def test_refresh_token_rejected_as_access(self) -> None:
        with pytest.raises(TokenError):
            decode_token(create_refresh_token("alice"), "access")

    def test_expired_token_rejected(self) -> None:
        expired = jwt.encode(
            {
                "sub": "alice",
                "type": "access",
                "exp": datetime.now(UTC) - timedelta(minutes=1),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError):
            decode_token(expired, "access")

    def test_token_signed_with_other_secret_rejected(self) -> None:
        forged = jwt.encode(
            {
                "sub": "alice",
                "type": "access",
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            "a-different-secret-entirely",
            algorithm="HS256",
        )
        with pytest.raises(TokenError):
            decode_token(forged, "access")

    def test_unsigned_token_rejected(self) -> None:
        """`alg: none` is the classic JWT bypass -- the decoder must not accept
        a token that carries no signature at all."""
        unsigned = jwt.encode(
            {"sub": "alice", "type": "access", "exp": datetime.now(UTC) + timedelta(hours=1)},
            key="",
            algorithm="none",
        )
        with pytest.raises(TokenError):
            decode_token(unsigned, "access")

    def test_token_without_type_claim_rejected(self) -> None:
        no_type = jwt.encode(
            {"sub": "alice", "exp": datetime.now(UTC) + timedelta(hours=1)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError):
            decode_token(no_type, "access")

    def test_tokens_are_unique(self) -> None:
        """The jti claim makes each token individually identifiable, which is
        what a future revocation list would key on."""
        assert create_access_token("alice") != create_access_token("alice")
