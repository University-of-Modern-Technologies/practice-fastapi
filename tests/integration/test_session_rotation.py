"""Scenario 3 — refresh sessions against the real `sessions` table.

The rotation rule is easy to state and easy to get wrong: refreshing reuses the
row and replaces the secret. Get it wrong in one direction and a stolen token
keeps working; get it wrong in the other and the user's device list grows by one
entry every fifteen minutes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import UnauthorizedError
from app.core.security import verify_password
from app.db.models.user import Session as SessionRow
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import AuthService, split_refresh_token
from app.modules.auth.types import AuthConfig
from tests.integration.conftest import SEED_PASSWORD, create_user

CONFIG = AuthConfig(
    access_token_secret="integration-secret-value-that-is-long-enough",
    secure_cookies=False,
)


async def _login(session: AsyncSession, email: str) -> tuple[AuthService, str]:
    service = AuthService(session, CONFIG)
    result = await service.login(LoginRequest(email=email, password=SEED_PASSWORD))
    return service, result.refresh_token


async def test_signing_in_stores_a_digest_not_the_token(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.flush()

    _, refresh_token = await _login(db_session, user.email)

    session_id, secret = split_refresh_token(refresh_token)
    row = await db_session.get(SessionRow, session_id)
    assert row is not None
    assert row.user_id == user.id
    # The secret itself is never stored; only something that can confirm it.
    assert secret not in row.token_hash
    assert verify_password(secret, row.token_hash)


async def test_refresh_rotates_the_secret_inside_the_same_row(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    service, first_token = await _login(db_session, user.email)
    sessions_after_login = await db_session.scalar(
        select(func.count()).select_from(SessionRow).where(SessionRow.user_id == user.id)
    )

    second = await service.refresh(first_token)

    first_id, first_secret = split_refresh_token(first_token)
    second_id, second_secret = split_refresh_token(second.refresh_token)
    # One session, one row: the device list does not grow with every refresh.
    assert second_id == first_id
    assert (
        await db_session.scalar(
            select(func.count()).select_from(SessionRow).where(SessionRow.user_id == user.id)
        )
        == sessions_after_login
    )

    row = await db_session.get(SessionRow, first_id)
    assert row is not None
    # The old half stops working the moment the legitimate holder refreshes,
    # which is what limits the damage a stolen token can do.
    assert verify_password(second_secret, row.token_hash)
    assert not verify_password(first_secret, row.token_hash)


async def test_a_rotated_token_is_refused(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    service, first_token = await _login(db_session, user.email)
    await service.refresh(first_token)

    with pytest.raises(UnauthorizedError) as failure:
        await service.refresh(first_token)

    assert failure.value.code == "INVALID_REFRESH_TOKEN"


async def test_logging_out_revokes_the_row_and_ends_the_session(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    service, refresh_token = await _login(db_session, user.email)
    session_id, _ = split_refresh_token(refresh_token)

    await service.logout(refresh_token)
    await db_session.flush()
    db_session.expire_all()

    row = await db_session.get(SessionRow, session_id)
    assert row is not None
    assert row.revoked_at is not None
    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token)


async def test_a_disabled_account_cannot_sign_in(db_session: AsyncSession) -> None:
    user = await create_user(db_session, is_active=False)
    service = AuthService(db_session, CONFIG)

    with pytest.raises(UnauthorizedError) as failure:
        await service.login(LoginRequest(email=user.email, password=SEED_PASSWORD))

    # A disabled account, a wrong password and a missing account are one answer:
    # any difference between them turns the endpoint into an account oracle.
    assert failure.value.code == "INVALID_CREDENTIALS"
