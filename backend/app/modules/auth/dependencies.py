"""Everything other modules need in order to require a signed-in caller.

``CurrentAuth`` is the single import a domain router should need: it produces an
``AuthContext`` or fails the request, and no handler ever sees a half-verified
identity.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.core.settings import Settings, get_settings
from app.db.session import get_session
from app.modules.auth.service import AuthService
from app.modules.auth.types import (
    AuthConfig,
    AuthContext,
    ClientInfo,
    NoopSessionRevocationListener,
    SessionRevocationListener,
    auth_config_from_settings,
)

#: ``auto_error`` is off because the framework's own rejection would be a 403
#: with a ``detail`` body — neither the status nor the shape this API promises.
_bearer_scheme = HTTPBearer(auto_error=False, description="Access token issued by /auth/login")

#: The request's database session.
#:
#: ``scope="function"`` is what makes the response honest. A dependency with
#: yield is torn down at the end of the *request* by default, and the framework
#: sends the response before that happens — so the client could read a 201 while
#: the transaction that created the row was still open, and a follow-up request
#: issued on the heels of it would legitimately answer "not found". Closing the
#: dependency at the end of the *function* instead puts the commit before the
#: first byte of the response, which is the order a client is entitled to assume.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_app_settings(request: Request) -> Settings:
    """The configuration this application was built with.

    The lifespan publishes it on the application state; the process-wide
    singleton is the fallback for an application assembled without one.
    """
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def get_auth_config(settings: SettingsDep) -> AuthConfig:
    return auth_config_from_settings(settings)


AuthConfigDep = Annotated[AuthConfig, Depends(get_auth_config)]


def get_client_info(request: Request) -> ClientInfo:
    """The caller's address and user agent.

    The address is the peer of the connection rather than a forwarded header:
    the header is whatever the client chose to send, and a session record that
    repeats a claim is worse than one that records nothing.
    """
    client = request.client
    return ClientInfo.of(client.host if client else None, request.headers.get("user-agent"))


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]


_NO_LISTENER = NoopSessionRevocationListener()


def get_session_revocations(request: Request) -> SessionRevocationListener:
    """Whatever must hear about ended sessions: the realtime gateway, if one runs.

    Resolved from the application state, like the event publisher, and a no-op
    for an application assembled without one — the case in unit tests.
    """
    listener = getattr(request.app.state, "realtime", None)
    if isinstance(listener, SessionRevocationListener):
        return listener
    return _NO_LISTENER


SessionRevocationsDep = Annotated[SessionRevocationListener, Depends(get_session_revocations)]


def get_auth_service(
    session: SessionDep,
    config: AuthConfigDep,
    client: ClientInfoDep,
    sessions: SessionRevocationsDep,
) -> AuthService:
    return AuthService(session, config, client, sessions)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    service: AuthServiceDep,
) -> AuthContext:
    """Resolves the caller from the ``Authorization`` header."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise UnauthorizedError()
    return await service.authenticate(credentials.credentials)


#: The identity of the current caller. Import this, not the function.
CurrentAuth = Annotated[AuthContext, Depends(get_auth)]
