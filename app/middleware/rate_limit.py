"""Request rate limiting.

A sliding window kept in Redis: each request is recorded with its timestamp,
entries older than the window are dropped, and the count of what remains decides
the verdict. A sliding window is used rather than a fixed one because a fixed
window lets a client spend two full budgets back to back across the boundary.

The whole decision is one Lua script so that trimming, counting and recording
cannot interleave with another request between them.
"""

from __future__ import annotations

import ipaddress
import time
import uuid
from collections.abc import Sequence
from typing import Any, Protocol

import jwt
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.handlers import error_response
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.core.settings import Settings

logger = get_logger("rate-limit")

RATE_LIMIT_ERROR_CODE = "RATE_LIMIT_EXCEEDED"
RATE_LIMIT_MESSAGE = "Too many requests, please try again later"

RATE_LIMIT_NAMESPACE = "rate-limit:"
AUTH_RATE_LIMIT_NAMESPACE = "rate-limit:auth:"

#: Authentication endpoints carry a second, much smaller budget on top of the
#: global one: they are the ones worth guessing against.
AUTH_PATH_PREFIX = "/api/v1/auth"

# A single IPv6 client is normally handed a whole /64, so the budget is applied
# per subnet rather than per address, which the client can rotate at will.
IPV6_SUBNET_BITS = 64
IPV6_VERSION = 6

# KEYS[1] window key, ARGV: now(ms), window(ms), limit, member
# Returns {allowed, remaining, reset_after_ms}.
SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local used = redis.call('ZCARD', key)

-- Time until the oldest recorded request leaves the window, i.e. until a slot
-- frees up. With nothing recorded yet a fresh entry lasts a whole window.
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local reset = window
if oldest[2] then
  reset = tonumber(oldest[2]) + window - now
end

if used < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, window)
  return {1, limit - used - 1, reset}
end

redis.call('PEXPIRE', key, window)
return {0, 0, reset}
"""


class RateLimitRedis(Protocol):
    """The raw script channel, declared structurally so a double is trivial."""

    async def eval_script(self, script: str, keys: Sequence[str], args: Sequence[str]) -> Any: ...


BEARER_PREFIX = "bearer "


def bearer_subject(scope: Scope, secret: str) -> str | None:
    """The signed-in user's id, when the request carries a valid access token.

    A *signature-verified* read of one claim, and nothing more: no session
    lookup, no account state, no error. Anything unusable — no header, a
    malformed one, a bad signature, an expired or non-access token — returns
    ``None`` so the caller falls back to the peer address. Rejecting here would
    turn the limiter into a second, weaker authenticator that answers 401 before
    the real one ever runs.
    """
    raw = next(
        (value for key, value in scope.get("headers", ()) if key == b"authorization"),
        None,
    )
    if raw is None:
        return None

    try:
        header = raw.decode("latin-1")
    except UnicodeDecodeError:
        return None
    if not header.lower().startswith(BEARER_PREFIX):
        return None

    try:
        claims = decode_access_token(header[len(BEARER_PREFIX) :].strip(), secret)
    except jwt.PyJWTError:
        return None

    subject = claims.get("sub")
    if claims.get("type") != "access" or not isinstance(subject, str) or not subject:
        return None
    return subject


def client_identity(scope: Scope) -> str:
    """Identifies the caller a budget belongs to by address.

    The peer address is used as-is: forwarded headers are attacker-controlled
    unless a trusted proxy rewrites them, and treating them as identity would
    hand every client an unlimited supply of budgets.
    """
    client = scope.get("client")
    host = str(client[0]) if client else ""
    if not host:
        return "unknown"

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host

    if address.version == IPV6_VERSION:
        network = ipaddress.ip_network(f"{host}/{IPV6_SUBNET_BITS}", strict=False)
        return str(network)
    return host


class RateLimitMiddleware:
    """Rejects a caller that exceeded its budget with HTTP 429.

    Written as raw ASGI, like the rest of the stack, so the limit applies before
    a request body is read or a route is resolved.
    """

    def __init__(self, app: ASGIApp, *, redis: RateLimitRedis, settings: Settings) -> None:
        self.app = app
        self.redis = redis
        self.window_ms = settings.rate_limit_window_seconds * 1_000
        self.max_requests = settings.rate_limit_max_requests
        self.auth_max_requests = settings.auth_rate_limit_max_requests
        self.key_prefix = settings.redis_key_prefix
        self.access_token_secret = settings.jwt_access_secret

    def _budgets(self, path: str) -> tuple[tuple[int, str], ...]:
        """The budgets a request spends, in the order they are spent.

        Every request spends the global one. A request to an authentication
        endpoint spends the much smaller auth budget *as well* — those are the
        endpoints worth guessing against, so the narrower limit is an extra
        constraint, not a replacement for the general one.
        """
        general = (self.max_requests, RATE_LIMIT_NAMESPACE)
        if path.startswith(AUTH_PATH_PREFIX):
            return general, (self.auth_max_requests, AUTH_RATE_LIMIT_NAMESPACE)
        return (general,)

    def _identity(self, scope: Scope) -> str:
        """Who the budget belongs to: the signed-in user, else the address.

        Keying by user is what makes the limit fair behind NAT, where an entire
        office shares one address and would otherwise share one budget.
        """
        subject = bearer_subject(scope, self.access_token_secret)
        return f"user:{subject}" if subject is not None else client_identity(scope)

    async def _consume(self, key: str, limit: int, now_ms: int) -> tuple[bool, int, int]:
        """Spends one slot of a budget. Returns (allowed, remaining, reset_ms)."""
        verdict = await self.redis.eval_script(
            SLIDING_WINDOW_SCRIPT,
            [key],
            [str(now_ms), str(self.window_ms), str(limit), f"{now_ms}-{uuid.uuid4().hex}"],
        )
        allowed, remaining, reset_ms = (int(item) for item in verdict)
        return bool(allowed), remaining, reset_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        identity = self._identity(scope)
        now_ms = int(time.time() * 1000)
        limit, remaining, reset_ms, denied = 0, 0, 0, False

        try:
            for limit, namespace in self._budgets(scope.get("path", "")):
                # The script addresses the key directly, so the deployment-wide
                # prefix has to be part of the key the application composes.
                key = f"{self.key_prefix}{namespace}{identity}"
                allowed, remaining, reset_ms = await self._consume(key, limit, now_ms)
                if not allowed:
                    # Short-circuit: a budget already refused, so the narrower
                    # one behind it is left unspent rather than charged for a
                    # request that is not going to be served.
                    denied = True
                    break
        except Exception as error:
            # Fail open: the limiter protects against load, and a Redis outage is
            # already load. Rejecting traffic here would turn a cache incident
            # into an outage of the API itself.
            logger.warning("Rate limit check failed, allowing the request", err=repr(error))
            await self.app(scope, receive, send)
            return

        # Seconds still to run before the budget frees up — not the window size.
        reset_seconds = max(0, -(-reset_ms // 1000))
        policy = f"{limit};w={self.window_ms // 1000}"

        if denied:
            logger.warning(
                "Rate limit exceeded",
                method=scope.get("method"),
                path=scope.get("path"),
            )
            response = error_response(
                status_code=429,
                code=RATE_LIMIT_ERROR_CODE,
                message=RATE_LIMIT_MESSAGE,
            )
            response.headers["retry-after"] = str(max(1, reset_seconds))
            response.headers["ratelimit-policy"] = policy
            response.headers["ratelimit"] = f"limit={limit}, remaining=0, reset={reset_seconds}"
            await response(scope, receive, send)
            return

        # IETF draft-7 combined form, the shape the sibling deployment emits.
        # The narrowest budget spent is the one reported, which is what the
        # sibling ends up sending when its two limiters write in turn.
        headers = [
            (b"ratelimit-policy", policy.encode("latin-1")),
            (
                b"ratelimit",
                f"limit={limit}, remaining={remaining}, reset={reset_seconds}".encode("latin-1"),
            ),
        ]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *headers]}
            await send(message)

        await self.app(scope, receive, send_with_headers)
