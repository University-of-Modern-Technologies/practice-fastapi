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
from fastapi.concurrency import run_in_threadpool

#: Work factor for password hashing. Matches the sibling backend so a seeded
#: account can sign in to either one.
BCRYPT_ROUNDS = 12

#: bcrypt reads at most this many bytes of its input. A longer password is
#: refused at the boundary rather than silently cut, which would make every
#: password sharing the first 72 bytes equivalent.
MAX_PASSWORD_BYTES = 72

#: Digest of a throwaway password at the same work factor. A login for an
#: address nobody holds is checked against it, so that case costs the same time
#: as a wrong password and the response time does not reveal who has an account.
DUMMY_PASSWORD_HASH = "$2b$12$soN8xmLrWH9xCYwHeAVBkOt4WUf5yW5q.SsjqUgDsdBU5KcA6simC"

ALGORITHM = "HS256"


def ensure_password_fits(password: str) -> str:
    """Rejects a password longer than bcrypt can take, counted in UTF-8 bytes."""
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        message = f"Password must not exceed {MAX_PASSWORD_BYTES} bytes"
        raise ValueError(message)
    return password


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


async def hash_password_async(password: str) -> str:
    """``hash_password`` on a worker thread.

    A digest at this work factor is a quarter of a second of CPU; computed on
    the event loop it would stall every other request for that long.
    """
    return await run_in_threadpool(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """``verify_password`` on a worker thread, for the same reason."""
    return await run_in_threadpool(verify_password, password, password_hash)


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
