"""HTTP surface of the ledger.

Eight endpoints, and only one of them talks to the bank. That split is
deliberate: ``POST /finance/statements/import`` is where a third party's bad
day can reach us, and it is the only place it can. Browsing the ledger,
matching a payment and running the rule all work on what a previous import
already stored, so a bank that is unreachable costs this module one endpoint
rather than all of it.

The provider is resolved from the application rather than built per request:
constructing one per call would re-emit the "running on the stub" warning on
every import.

This module has no ``OWN`` narrowing to apply, and the absence is the point.
A bank statement belongs to the company, not to a colleague, so the scope is
carried for uniformity and acted on nowhere — the reasoning is written out on
``FinanceAccess``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from app.core.logging import get_logger
from app.core.openapi import refusals
from app.core.responses import Envelope, Page
from app.db.enums import PermissionScope
from app.events.dependencies import PublisherDep
from app.modules.auth.dependencies import CurrentAuth, SessionDep
from app.modules.finance.provider import BankProvider
from app.modules.finance.schemas import (
    BankStatementOut,
    BankTransactionDetailOut,
    BankTransactionOut,
    FinanceSummaryOut,
    FinanceSummaryParams,
    ImportStatementOut,
    MatchTransactionRequest,
    ReconcileOut,
    StatementListParams,
    TransactionListParams,
)
from app.modules.finance.service import FinanceService
from app.modules.finance.stub_provider import create_stub_bank_provider
from app.modules.finance.types import FinanceAccess
from app.modules.rbac.dependencies import require_permission

__all__ = [
    "STUB_PROVIDER_WARNING",
    "FinanceServiceDep",
    "create_finance_router",
    "get_bank_provider",
    "get_finance_service",
]

RESOURCE = "finance"

logger = get_logger("finance.provider")

STUB_PROVIDER_WARNING = (
    "No bank provider configured; using the built-in offline stub. "
    "Imported statements are fixtures, not account activity."
)

ReadScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "read"))]
WriteScope = Annotated[PermissionScope, Depends(require_permission(RESOURCE, "write"))]

StatementParams = Annotated[StatementListParams, Query()]
TransactionParams = Annotated[TransactionListParams, Query()]
SummaryParams = Annotated[FinanceSummaryParams, Query()]
TransactionVersion = Annotated[int, Query(ge=1)]


def get_bank_provider(request: Request) -> BankProvider:
    """The bank this application imports from, built once and remembered.

    Nothing configured means the offline stub, which is what keeps a fresh
    checkout able to import, reconcile and report with no account and no
    network.
    """
    provider = getattr(request.app.state, "bank_provider", None)
    if provider is None:
        logger.warning(STUB_PROVIDER_WARNING)
        provider = create_stub_bank_provider()
        request.app.state.bank_provider = provider
    return cast("BankProvider", provider)


BankProviderDep = Annotated[BankProvider, Depends(get_bank_provider)]


def get_finance_service(
    session: SessionDep,
    provider: BankProviderDep,
    publisher: PublisherDep,
) -> FinanceService:
    return FinanceService(session, provider, publisher)


FinanceServiceDep = Annotated[FinanceService, Depends(get_finance_service)]


def _client_ip(request: Request) -> str | None:
    """The address the audit trail records the change against.

    Read from the connection rather than from a forwarded header: the header
    is caller-controlled, and an audit entry that records whatever the client
    claimed is worse than one that records nothing.
    """
    return request.client.host if request.client is not None else None


def _access(auth: CurrentAuth, request: Request, scope: PermissionScope) -> FinanceAccess:
    return FinanceAccess(actor_id=auth.user_id, scope=scope, ip_address=_client_ip(request))


# Identity, breadth of grant and client address are resolved together, so a
# handler takes one argument instead of three and cannot forget one of them.
async def get_read_access(auth: CurrentAuth, request: Request, scope: ReadScope) -> FinanceAccess:
    return _access(auth, request, scope)


async def get_write_access(auth: CurrentAuth, request: Request, scope: WriteScope) -> FinanceAccess:
    return _access(auth, request, scope)


ReadAccess = Annotated[FinanceAccess, Depends(get_read_access)]
WriteAccess = Annotated[FinanceAccess, Depends(get_write_access)]


def create_finance_router() -> APIRouter:
    """Builds the router; the prefix is applied by the application factory."""
    router = APIRouter(tags=["Finance"])

    @router.get(
        "/statements", summary="Переглянути банківські виписки", responses=refusals(401, 403)
    )
    async def list_statements(
        access: ReadAccess,
        service: FinanceServiceDep,
        params: StatementParams,
    ) -> Envelope[Page[BankStatementOut]]:
        items, total = await service.list_statements(access, params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.post(
        "/statements/import",
        summary="Імпортувати виписку з банку",
        description="Повторний виклик не створює дублів: ключ ідемпотентності — `externalId`. "
        "Недоступний банк — 502 `BANK_PROVIDER_UNAVAILABLE`.",
        responses=refusals(401, 403, 409, 502),
    )
    async def import_statement(
        access: WriteAccess,
        service: FinanceServiceDep,
    ) -> Envelope[ImportStatementOut]:
        return Envelope(data=await service.import_statement(access))

    @router.get(
        "/transactions", summary="Переглянути банківські транзакції", responses=refusals(401, 403)
    )
    async def list_transactions(
        access: ReadAccess,
        service: FinanceServiceDep,
        params: TransactionParams,
    ) -> Envelope[Page[BankTransactionOut]]:
        items, total = await service.list_transactions(access, params)
        return Envelope(
            data=Page(items=items, page=params.page, page_size=params.page_size, total=total)
        )

    @router.get(
        "/transactions/{id}",
        summary="Отримати транзакцію",
        # The published description is Ukrainian and has to match the sibling
        # backend character for character, so the Cyrillic letters whose shapes
        # are also Latin stay exactly as they are.
        description="Для стану `SUGGESTED` у відповіді — перелік замовлень-кандидатів.",  # noqa: RUF001,
        responses=refusals(401, 403, 404),
    )
    async def get_transaction(
        id: uuid.UUID,  # noqa: A002
        access: ReadAccess,
        service: FinanceServiceDep,
    ) -> Envelope[BankTransactionDetailOut]:
        return Envelope(data=await service.get_transaction(access, id))

    @router.post(
        "/transactions/{id}/match",
        summary="Звести транзакцію із замовленням",
        responses=refusals(401, 403, 404, 409, 422),
    )
    async def match_transaction(
        id: uuid.UUID,  # noqa: A002
        payload: MatchTransactionRequest,
        access: WriteAccess,
        service: FinanceServiceDep,
    ) -> Envelope[BankTransactionOut]:
        return Envelope(data=await service.match(access, id, payload))

    @router.delete(
        "/transactions/{id}/match",
        summary="Зняти зведення транзакції",
        responses=refusals(401, 403, 404, 409),
    )
    async def unmatch_transaction(
        id: uuid.UUID,  # noqa: A002
        version: TransactionVersion,
        access: WriteAccess,
        service: FinanceServiceDep,
    ) -> Envelope[BankTransactionOut]:
        return Envelope(data=await service.unmatch(access, id, version))

    @router.post(
        "/reconcile",
        summary="Виконати автозведення платежів",
        description="Правило застосовується лише до надходжень у станах "  # noqa: RUF001
        "`UNMATCHED` і `SUGGESTED`.",  # noqa: RUF001,
        responses=refusals(401, 403),
    )
    async def reconcile(
        access: WriteAccess,
        service: FinanceServiceDep,
    ) -> Envelope[ReconcileOut]:
        return Envelope(data=await service.reconcile(access))

    @router.get(
        "/summary", summary="Отримати фінансовий підсумок за період", responses=refusals(401, 403)
    )
    async def finance_summary(
        access: ReadAccess,
        service: FinanceServiceDep,
        params: SummaryParams,
    ) -> Envelope[FinanceSummaryOut]:
        return Envelope(data=await service.summary(access, params))

    return router
