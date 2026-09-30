"""HTTP surface of authentication.

The handlers are the only place that knows about the refresh cookie: the token
never appears in a response body, so a script on the page cannot read it even if
one is injected.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status

from app.core.errors import UnauthorizedError
from app.core.openapi import refusals
from app.core.responses import Envelope
from app.modules.auth.dependencies import AuthConfigDep, AuthServiceDep, CurrentAuth
from app.modules.auth.schemas import AuthenticatedUser, AuthPayload, LoginRequest
from app.modules.auth.types import (
    REFRESH_COOKIE_NAME,
    AuthConfig,
    AuthResult,
    refresh_cookie_kwargs,
)

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)]


def _set_refresh_cookie(response: Response, config: AuthConfig, refresh_token: str) -> None:
    response.set_cookie(
        value=refresh_token,
        max_age=config.refresh_token_ttl_seconds,
        **refresh_cookie_kwargs(config),
    )


def _to_payload(result: AuthResult) -> Envelope[AuthPayload]:
    return Envelope(
        data=AuthPayload(
            user=result.user,
            access_token=result.access_token,
            access_token_expires_in_seconds=result.access_token_expires_in_seconds,
        )
    )


def create_auth_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Auth"])

    @router.post("/login", summary="Увійти до системи", responses=refusals(401))
    async def login(
        payload: LoginRequest,
        response: Response,
        service: AuthServiceDep,
        config: AuthConfigDep,
    ) -> Envelope[AuthPayload]:
        result = await service.login(payload)
        _set_refresh_cookie(response, config, result.refresh_token)
        return _to_payload(result)

    @router.post("/refresh", summary="Оновити пару токенів", responses=refusals(401))
    async def refresh(
        response: Response,
        service: AuthServiceDep,
        config: AuthConfigDep,
        refresh_token: RefreshCookie = None,
    ) -> Envelope[AuthPayload]:
        if not refresh_token:
            raise UnauthorizedError("Refresh token is required", "REFRESH_TOKEN_REQUIRED")
        result = await service.refresh(refresh_token)
        _set_refresh_cookie(response, config, result.refresh_token)
        return _to_payload(result)

    @router.post(
        "/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        summary="Завершити refresh-сесію",
    )
    async def logout(
        service: AuthServiceDep,
        config: AuthConfigDep,
        refresh_token: RefreshCookie = None,
    ) -> Response:
        await service.logout(refresh_token)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        # Clearing is unconditional: a caller whose cookie was already invalid
        # still expects the browser to stop sending it.
        response.delete_cookie(**refresh_cookie_kwargs(config))
        return response

    @router.get("/me", summary="Отримати поточного користувача", responses=refusals(401))
    async def me(auth: CurrentAuth, service: AuthServiceDep) -> Envelope[AuthenticatedUser]:
        return Envelope(data=await service.me(auth.user_id))

    return router
