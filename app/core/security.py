"""Password hashing and access-token signing.

Both primitives are deliberately thin wrappers: the cost factor and the token
claims are the parts worth naming, and everything else is delegated to the
underlying library.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

#: Work factor for password hashing. Matches the sibling backend so a seeded
#: account can sign in to either one.
BCRYPT_ROUNDS = 12

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Returns a salted bcrypt digest."""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time comparison of a candidate against a stored digest."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # A malformed stored hash must read as "wrong password", never as an
        # error the caller has to handle — otherwise a corrupt row becomes a 500.
        return False


def create_access_token(
    *,
    subject: str,
    session_id: str,
    secret: str,
    ttl_seconds: int,
) -> str:
    """Signs a short-lived access token bound to a specific session."""
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "sessionId": session_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    """Verifies a token and returns its claims.

    Raises ``jwt.PyJWTError`` for anything invalid; the caller decides which
    HTTP status that becomes.
    """
    claims: dict[str, Any] = jwt.decode(token, secret, algorithms=[ALGORITHM])
    return claims
