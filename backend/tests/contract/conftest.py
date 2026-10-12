"""Fixtures for the contract suite.

The suite answers one question: does the wire format this application produces
match the published contract, byte for byte, in the twelve places where a
Python implementation drifts away from it by default.

Nothing here touches storage. Where a check would otherwise need a database,
the session or the whole domain service is replaced by a double, because the
subject under test is the shape that leaves the process, not the query that
produced it.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, Query
from httpx import ASGITransport, AsyncClient
from pydantic import Field

from app.core.errors import ConflictError, VersionConflictError
from app.core.responses import CamelModel, Envelope, Page
from app.core.serializers import Money, UtcDatetime
from app.core.settings import Settings
from app.db.enums import DealStage, OrderStatus, PermissionScope
from app.factory import create_app
from app.health.lifecycle import service_lifecycle
from app.modules.ai import create_ai_router
from app.modules.analytics import create_analytics_router
from app.modules.audit import create_audit_router
from app.modules.auth import create_auth_router
from app.modules.auth.dependencies import get_auth, get_auth_service
from app.modules.auth.schemas import AuthenticatedUser, PermissionOut
from app.modules.auth.types import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_SECRET_BYTES,
    REFRESH_TOKEN_SEPARATOR,
    AuthContext,
    AuthResult,
)
from app.modules.contacts import create_contacts_router
from app.modules.contacts.router import get_contacts_service
from app.modules.contacts.schemas import (
    ContactListParams,
    ContactOut,
    CreateContactRequest,
    UpdateContactRequest,
)
from app.modules.contacts.types import ContactAccess
from app.modules.deals import create_deals_router
from app.modules.deals.types import DEAL_CONCURRENT_MODIFICATION
from app.modules.integrations import create_integrations_router
from app.modules.orders import create_orders_router
from app.modules.orders.types import ORDER_CONCURRENT_MODIFICATION
from app.modules.products import create_products_router
from app.modules.products.types import PRODUCT_CONCURRENT_MODIFICATION
from app.modules.rbac.dependencies import get_rbac_service
from app.modules.rbac.router import create_rbac_router
from app.modules.settings import create_settings_router
from app.modules.users import create_users_router
from app.modules.warehouse import create_warehouse_router
from app.modules.warehouse.types import STOCK_CONCURRENT_MODIFICATION

API_PREFIX = "/api/v1"

#: The address `ASGITransport` reports as the peer of every in-process request.
TRANSPORT_CLIENT_HOST = "127.0.0.1"

ACTOR_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
SESSION_ID = uuid.UUID("11000000-0000-4000-8000-000000000001")
CONTACT_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")

#: Same instant expressed three ways: without a zone, in a zone that is not UTC,
#: and with more precision than the contract allows.
NAIVE_MOMENT = datetime(2026, 8, 12, 15, 23, 45, 123_456)  # noqa: DTZ001
SHIFTED_MOMENT = datetime(2026, 8, 12, 17, 23, 45, 123_000, tzinfo=timezone(timedelta(hours=2)))
SUB_MILLISECOND_MOMENT = datetime(2026, 8, 12, 15, 23, 45, 999_999, tzinfo=UTC)

AUTHENTICATED_USER = AuthenticatedUser(
    id=ACTOR_ID,
    email="morgan@example.com",
    name="Morgan Manager",
    roles=["manager"],
    permissions=[PermissionOut(resource="contacts", action="read", scope=PermissionScope.ALL)],
)

#: Every machine code the optimistic-locking guard may report, by resource.
CONCURRENT_MODIFICATION_CODES = {
    "deal": ("Deal was modified by another request", DEAL_CONCURRENT_MODIFICATION),
    "order": ("Order was modified by another request", ORDER_CONCURRENT_MODIFICATION),
    "product": ("Product was modified by another request", PRODUCT_CONCURRENT_MODIFICATION),
    "stock": (
        "Stock level was modified by another request; retry the operation",
        STOCK_CONCURRENT_MODIFICATION,
    ),
}


class ProbeBody(CamelModel):
    """Body of the probe endpoint that exists only to be violated."""

    email_address: str = Field(min_length=3)
    age: int = Field(ge=0)


class InstantOut(CamelModel):
    """Three timestamps that would each render differently without the field type."""

    naive_moment: UtcDatetime
    shifted_moment: UtcDatetime
    sub_millisecond_moment: UtcDatetime


class MoneyOut(CamelModel):
    """Amounts chosen to expose every way a decimal can be mis-rendered."""

    trailing_zero: Money
    already_short: Money
    zero: Money
    whole_thousands: Money
    two_decimals: Money


class EnumOut(CamelModel):
    stage: DealStage
    status: OrderStatus
    scope: PermissionScope


class ItemOut(CamelModel):
    id: uuid.UUID
    display_name: str
    created_at: UtcDatetime


def _create_probe_router() -> APIRouter:
    """Endpoints that exist only to drive the serialisation machinery."""
    router = APIRouter()

    @router.post("/body")
    async def echo_body(payload: ProbeBody) -> Envelope[ProbeBody]:
        return Envelope(data=payload)

    @router.get("/query")
    async def read_query(limit: int = Query(ge=1, le=100)) -> Envelope[dict[str, int]]:
        return Envelope(data={"limit": limit})

    @router.get("/item/{item_id}")
    async def read_item(item_id: uuid.UUID) -> Envelope[dict[str, str]]:
        return Envelope(data={"id": str(item_id)})

    @router.get("/instants")
    async def read_instants() -> Envelope[InstantOut]:
        return Envelope(
            data=InstantOut(
                naive_moment=NAIVE_MOMENT,
                shifted_moment=SHIFTED_MOMENT,
                sub_millisecond_moment=SUB_MILLISECOND_MOMENT,
            )
        )

    @router.get("/money")
    async def read_money() -> Envelope[MoneyOut]:
        return Envelope(
            data=MoneyOut(
                trailing_zero=Decimal("12.50"),
                already_short=Decimal("12.5"),
                zero=Decimal("0.00"),
                whole_thousands=Decimal("2400.00"),
                two_decimals=Decimal("19.99"),
            )
        )

    @router.get("/enums")
    async def read_enums() -> Envelope[EnumOut]:
        return Envelope(
            data=EnumOut(
                stage=DealStage.QUALIFIED,
                status=OrderStatus.CONFIRMED,
                scope=PermissionScope.OWN,
            )
        )

    @router.get("/page")
    async def read_page() -> Envelope[Page[ItemOut]]:
        items = [
            ItemOut(id=CONTACT_ID, display_name="Ada Byron", created_at=SUB_MILLISECOND_MOMENT)
        ]
        return Envelope(data=Page(items=items, page=2, page_size=20, total=41))

    @router.get("/version-conflict/{resource}")
    async def raise_version_conflict(resource: str) -> None:
        message, code = CONCURRENT_MODIFICATION_CODES[resource]
        raise VersionConflictError(message, code)

    @router.get("/bare-conflict")
    async def raise_bare_conflict() -> None:
        raise ConflictError("Contact already exists", "CONTACT_EXISTS")

    return router


def _build_app(settings: Settings, routers: list[tuple[str, APIRouter]]) -> FastAPI:
    """Assembles the real application around the given routers.

    The lifespan does not run under an in-process transport, so the readiness
    state and the settings are published the way it would have published them.
    """
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=routers)
    app.state.settings = settings
    return app


async def _open_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def probe_app(settings: Settings) -> FastAPI:
    return _build_app(settings, [("/probe", _create_probe_router())])


@pytest.fixture
async def probe_client(probe_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async for client in _open_client(probe_app):
        yield client


@dataclass(slots=True)
class RecordedCall:
    """One call the router made into the domain service."""

    method: str
    access: ContactAccess
    payload: Any = None


class RecordingContactsService:
    """Stands in for the contacts service and remembers what it was handed.

    The router's own decisions — which address it stamps an entry with, whether
    it preserves the difference between an absent field and an explicit null —
    are only observable from here.
    """

    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    @staticmethod
    def _contact() -> ContactOut:
        return ContactOut(
            id=CONTACT_ID,
            owner_id=ACTOR_ID,
            first_name="Ada",
            last_name="Byron",
            email="ada@example.com",
            phone="+380671234567",
            company="Analytical Engines",
            notes=None,
            created_at=SUB_MILLISECOND_MOMENT,
            updated_at=SUB_MILLISECOND_MOMENT,
        )

    async def list(
        self, access: ContactAccess, query: ContactListParams
    ) -> tuple[list[ContactOut], int]:
        self.calls.append(RecordedCall("list", access, query))
        return [self._contact()], 1

    async def get_by_id(self, access: ContactAccess, contact_id: uuid.UUID) -> ContactOut:
        self.calls.append(RecordedCall("get_by_id", access, contact_id))
        return self._contact()

    async def create(self, access: ContactAccess, data: CreateContactRequest) -> ContactOut:
        self.calls.append(RecordedCall("create", access, data))
        return self._contact()

    async def update(
        self, access: ContactAccess, contact_id: uuid.UUID, data: UpdateContactRequest
    ) -> ContactOut:
        # The patch body is what these tests read back, not the target id.
        del contact_id
        self.calls.append(RecordedCall("update", access, data))
        return self._contact()

    async def delete(self, access: ContactAccess, contact_id: uuid.UUID) -> None:
        self.calls.append(RecordedCall("delete", access, contact_id))

    @property
    def last(self) -> RecordedCall:
        return self.calls[-1]


class FakeRbacService:
    """Reports whatever breadth the test asked for, without a database."""

    def __init__(self, scope: PermissionScope = PermissionScope.ALL) -> None:
        self.scope = scope

    async def get_permission_scope(
        self, user_id: uuid.UUID, resource: str, action: str
    ) -> PermissionScope:
        del user_id, resource, action
        return self.scope


@pytest.fixture
def contacts_service() -> RecordingContactsService:
    return RecordingContactsService()


@pytest.fixture
def rbac_service() -> FakeRbacService:
    return FakeRbacService()


@pytest.fixture
def contacts_app(
    settings: Settings,
    contacts_service: RecordingContactsService,
    rbac_service: FakeRbacService,
) -> FastAPI:
    """The real contacts router with everything below the router replaced."""
    app = _build_app(settings, [(f"{API_PREFIX}/contacts", create_contacts_router())])
    app.dependency_overrides[get_auth] = lambda: AuthContext(
        user_id=ACTOR_ID, session_id=SESSION_ID
    )
    app.dependency_overrides[get_rbac_service] = lambda: rbac_service
    app.dependency_overrides[get_contacts_service] = lambda: contacts_service
    return app


@pytest.fixture
async def contacts_client(contacts_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async for client in _open_client(contacts_app):
        yield client


class FakeAuthService:
    """Issues real-shaped tokens without a database behind them.

    The secret is generated exactly the way the service generates it, because
    the token *format* is part of the contract: the client never parses it, but
    the sibling backend produces the same two halves and the same separator.
    """

    def __init__(self) -> None:
        self.issued: list[str] = []

    def _result(self) -> AuthResult:
        secret = secrets.token_urlsafe(REFRESH_SECRET_BYTES)
        token = f"{SESSION_ID}{REFRESH_TOKEN_SEPARATOR}{secret}"
        self.issued.append(token)
        return AuthResult(
            user=AUTHENTICATED_USER,
            access_token="issued-access-token",
            refresh_token=token,
            access_token_expires_in_seconds=ACCESS_TOKEN_TTL_SECONDS,
        )

    async def login(self, data: object) -> AuthResult:
        del data
        return self._result()

    async def refresh(self, refresh_token: str) -> AuthResult:
        del refresh_token
        return self._result()

    async def logout(self, refresh_token: str | None) -> None:
        del refresh_token

    async def me(self, user_id: uuid.UUID) -> AuthenticatedUser:
        del user_id
        return AUTHENTICATED_USER


@pytest.fixture
def auth_service() -> FakeAuthService:
    return FakeAuthService()


@pytest.fixture
def auth_app(settings: Settings, auth_service: FakeAuthService) -> FastAPI:
    app = _build_app(settings, [(f"{API_PREFIX}/auth", create_auth_router())])
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    return app


@pytest.fixture
async def auth_client(auth_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async for client in _open_client(auth_app):
        yield client


def all_routers() -> list[tuple[str, APIRouter]]:
    """Every router the running application mounts.

    Listed here rather than taken from the composition root because building
    that root also builds clients for three data stores, and this suite is
    supposed to work with none of them running.
    """
    factories: list[tuple[str, Callable[[], APIRouter]]] = [
        ("auth", create_auth_router),
        ("rbac", create_rbac_router),
        ("users", create_users_router),
        ("audit", create_audit_router),
        ("contacts", create_contacts_router),
        ("deals", create_deals_router),
        ("products", create_products_router),
        ("orders", create_orders_router),
        ("warehouse", create_warehouse_router),
        ("settings", create_settings_router),
        ("analytics", create_analytics_router),
        ("integrations", create_integrations_router),
        ("ai", create_ai_router),
    ]
    return [(f"{API_PREFIX}/{name}", factory()) for name, factory in factories]


@pytest.fixture(scope="session")
def openapi_schema() -> dict[str, Any]:
    """The published schema of the whole API, generated without any storage."""
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://user:pass@localhost:5432/practice_crm_test",
        jwt_access_secret="contract-secret-value-that-is-long-enough",
        jwt_refresh_secret="contract-secret-value-that-is-long-enough",
        redis_url="redis://localhost:6379",
        mongodb_url="mongodb://localhost:27017/practice_events_test",
    )
    service_lifecycle.reset()
    service_lifecycle.mark_started()
    app = create_app(settings, routers=all_routers())
    return app.openapi()


def resolve_ref(schema: dict[str, Any], node: Any) -> Any:
    """Follows a single ``$ref`` into the component section."""
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
        return node
    name = ref.rsplit("/", 1)[-1]
    components: dict[str, Any] = schema.get("components", {}).get("schemas", {})
    return components.get(name, {})


def iter_operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every (path, method, operation) triple in the published schema."""
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, item in schema.get("paths", {}).items():
        for method, operation in item.items():
            if isinstance(operation, dict):
                operations.append((path, method, operation))
    return operations
