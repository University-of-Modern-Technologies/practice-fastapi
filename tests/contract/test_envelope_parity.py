"""The twelve places where the wire format drifts, asserted directly.

Each section below corresponds to one item of the equivalence checklist. They
are grouped in one file on purpose: together they are the definition of "the
same contract", and a reader who wants to know what that phrase means should
have to open exactly one file.

Nothing here needs a database, a cache or an event log. Where a check would
otherwise reach storage, the session or the service is a double — the subject
is the shape that leaves the process, not the query behind it.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from http.cookies import SimpleCookie
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import VersionConflictError
from app.core.handlers import error_response
from app.core.responses import ErrorResponse
from app.core.serializers import format_datetime
from app.db.enums import DealStage, OrderStatus, PermissionScope, StockMovementType
from app.middleware.metrics import MetricsMiddleware
from app.middleware.request_id import REQUEST_ID_HEADER, RequestIdMiddleware
from app.middleware.request_logger import RequestLoggerMiddleware
from app.modules.audit import AuditEvent
from app.modules.auth.service import split_refresh_token
from app.modules.auth.types import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    REFRESH_TOKEN_SEPARATOR,
)
from app.modules.contacts.schemas import ContactListParams
from app.modules.contacts.service import ContactsService
from app.modules.contacts.types import ContactAccess
from tests.contract.conftest import (
    ACTOR_ID,
    CONCURRENT_MODIFICATION_CODES,
    CONTACT_ID,
    NAIVE_MOMENT,
    SHIFTED_MOMENT,
    SUB_MILLISECOND_MOMENT,
    TRANSPORT_CLIENT_HOST,
    FakeAuthService,
    RecordingContactsService,
    iter_operations,
    resolve_ref,
)

# ---------------------------------------------------------------------------
# 1. A schema violation is 400 with the error envelope, never 422 with `detail`
# ---------------------------------------------------------------------------


async def test_an_invalid_body_is_400_in_the_error_envelope(probe_client: AsyncClient) -> None:
    response = await probe_client.post("/probe/body", json={"emailAddress": "a", "age": -1})

    assert response.status_code == 400
    body = response.json()
    # The framework's own answer would be 422 with a `detail` array; neither
    # the status nor the key may reach a client.
    assert "detail" not in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert body["requestId"] == response.headers[REQUEST_ID_HEADER]


@pytest.mark.parametrize(
    ("request_args", "expected_location"),
    [
        pytest.param(
            {"method": "POST", "url": "/probe/body", "json": {"age": 1}},
            "body",
            id="body",
        ),
        pytest.param(
            {"method": "GET", "url": "/probe/query?limit=0"},
            "query",
            id="query",
        ),
        pytest.param(
            {"method": "GET", "url": "/probe/item/not-a-uuid"},
            "params",
            id="path",
        ),
    ],
)
async def test_every_part_of_a_request_reports_400(
    probe_client: AsyncClient,
    request_args: dict[str, Any],
    expected_location: str,
) -> None:
    response = await probe_client.request(**request_args)

    assert response.status_code == 400
    details = response.json()["error"]["details"]
    # `path` is the framework's word for it; the published contract says
    # `params`, and the client branches on that key.
    assert expected_location in details["fieldErrors"]


async def test_malformed_json_is_told_apart_from_a_wrong_shape(
    probe_client: AsyncClient,
) -> None:
    response = await probe_client.post(
        "/probe/body",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_JSON"


def test_the_published_schema_never_advertises_422(openapi_schema: dict[str, Any]) -> None:
    offenders = [
        f"{method.upper()} {path}"
        for path, method, operation in iter_operations(openapi_schema)
        if "422" in operation.get("responses", {})
    ]

    assert offenders == [], "A 422 in the schema is a promise this API never keeps"


def test_every_operation_documents_the_error_envelope(openapi_schema: dict[str, Any]) -> None:
    for path, method, operation in iter_operations(openapi_schema):
        responses = operation.get("responses", {})
        assert "400" in responses, f"{method.upper()} {path} does not document a 400"
        schema = responses["400"]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorResponse"}


# ---------------------------------------------------------------------------
# 2. Timestamps: UTC, exactly three fractional digits, `Z`
# ---------------------------------------------------------------------------

ISO_MILLISECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


async def test_timestamps_are_utc_with_three_digits_and_a_z(probe_client: AsyncClient) -> None:
    data = (await probe_client.get("/probe/instants")).json()["data"]

    for key, value in data.items():
        assert ISO_MILLISECONDS.match(value), f"{key} is rendered as {value!r}"

    # A value without a zone is read as UTC, not as local time: every timestamp
    # in this system comes out of a `timestamptz` column.
    assert data["naiveMoment"] == "2026-08-12T15:23:45.123Z"
    # A value in another zone is converted rather than annotated.
    assert data["shiftedMoment"] == "2026-08-12T15:23:45.123Z"
    # Sub-millisecond precision is truncated, never rounded up into the next
    # second — the sibling backend has no digits to round with.
    assert data["subMillisecondMoment"] == "2026-08-12T15:23:45.999Z"


def test_the_offset_form_python_would_produce_by_default_is_never_emitted() -> None:
    for moment in (NAIVE_MOMENT, SHIFTED_MOMENT, SUB_MILLISECOND_MOMENT):
        rendered = format_datetime(moment)
        assert "+" not in rendered
        assert rendered.endswith("Z")
        # `isoformat()` would give six fractional digits, or none at all.
        assert len(rendered.split(".")[1]) == len("123Z")


# ---------------------------------------------------------------------------
# 3. Money travels as a string, in the shortest exact form
# ---------------------------------------------------------------------------

#: A decimal string with no exponent, no leading `+` and no padding zeros
#: beyond the ones the value itself carries.
MONEY = re.compile(r"^-?(0|[1-9]\d*)(\.\d+)?$")


async def test_money_is_a_string_never_a_number(probe_client: AsyncClient) -> None:
    data = (await probe_client.get("/probe/money")).json()["data"]

    for key, value in data.items():
        assert isinstance(value, str), f"{key} left as a JSON number: {value!r}"
        assert MONEY.match(value), f"{key} is rendered as {value!r}"


async def test_money_is_rendered_in_the_shortest_exact_form(probe_client: AsyncClient) -> None:
    """The scale is not padded to two digits.

    This is the one place the equivalence checklist was wrong about its own
    subject: it asked for `quantize(Decimal("0.01"))`, which renders `12.5` as
    `"12.50"`. The reference implementation calls `toString()` on the decimal it
    read back, and that produces the shortest form that still names the value
    exactly. Two backends serving one client cannot disagree about this, so the
    reference wins and the checklist is the side that is corrected.
    """
    data = (await probe_client.get("/probe/money")).json()["data"]

    assert data["trailingZero"] == "12.5"
    assert data["alreadyShort"] == "12.5"
    assert data["zero"] == "0"
    # The trap inside the trap: `Decimal.normalize()` turns 2400.00 into
    # `2.4E+3`, which is a number no client will parse as money.
    assert data["wholeThousands"] == "2400"
    assert data["twoDecimals"] == "19.99"


async def test_money_never_loses_the_value_it_renders(probe_client: AsyncClient) -> None:
    data = (await probe_client.get("/probe/money")).json()["data"]

    expected = {
        "trailingZero": Decimal("12.50"),
        "alreadyShort": Decimal("12.5"),
        "zero": Decimal("0.00"),
        "wholeThousands": Decimal("2400.00"),
        "twoDecimals": Decimal("19.99"),
    }
    for key, amount in expected.items():
        assert Decimal(data[key]) == amount


# ---------------------------------------------------------------------------
# 4. PATCH: an absent field and an explicit null are different requests
# ---------------------------------------------------------------------------


async def test_an_omitted_field_is_not_part_of_the_patch(
    contacts_client: AsyncClient, contacts_service: RecordingContactsService
) -> None:
    response = await contacts_client.patch(
        f"/api/v1/contacts/{CONTACT_ID}", json={"company": "Analytical Engines"}
    )

    assert response.status_code == 200
    payload = contacts_service.last.payload
    assert payload.model_fields_set == {"company"}
    # Without this distinction every PATCH would blank every field the client
    # did not mention.
    assert "phone" not in payload.model_fields_set


async def test_an_explicit_null_is_part_of_the_patch(
    contacts_client: AsyncClient, contacts_service: RecordingContactsService
) -> None:
    response = await contacts_client.patch(f"/api/v1/contacts/{CONTACT_ID}", json={"phone": None})

    assert response.status_code == 200
    payload = contacts_service.last.payload
    assert "phone" in payload.model_fields_set
    assert payload.phone is None
    assert payload.model_dump(exclude_unset=True) == {"phone": None}


async def test_an_empty_patch_is_rejected(contacts_client: AsyncClient) -> None:
    response = await contacts_client.patch(f"/api/v1/contacts/{CONTACT_ID}", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_a_null_on_a_non_nullable_field_is_a_bad_request(
    contacts_client: AsyncClient,
) -> None:
    response = await contacts_client.patch(
        f"/api/v1/contacts/{CONTACT_ID}", json={"firstName": None}
    )

    # Nullable and optional are not the same permission: a name backs a
    # non-nullable column, so erasing it is a bad request rather than an edit.
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 5. Middleware order: the correlation id is established before the logger
# ---------------------------------------------------------------------------


def test_the_correlation_id_is_the_outermost_layer(probe_app: FastAPI) -> None:
    """`add_middleware` wraps from the outside in, so registration reverses.

    The list is read outermost-first. If these two ever swap, the access log
    line of every request loses its correlation id, and it does so silently.
    """
    stack = [cast("type[Any]", middleware.cls).__name__ for middleware in probe_app.user_middleware]

    assert stack[0] == RequestIdMiddleware.__name__
    assert stack[1] == RequestLoggerMiddleware.__name__
    # Metrics sit outside the guards so a throttled or rejected request is
    # still counted, but inside the two layers above.
    assert stack[2] == MetricsMiddleware.__name__


async def test_the_correlation_id_reaches_the_innermost_handler(
    probe_client: AsyncClient,
) -> None:
    inbound = "trace-0123456789"
    response = await probe_client.get("/probe/bare-conflict", headers={REQUEST_ID_HEADER: inbound})

    # The error envelope is produced by an exception handler — the innermost
    # layer of all — and it still sees the id, which is only true when the id
    # middleware runs first.
    assert response.headers[REQUEST_ID_HEADER] == inbound
    assert response.json()["requestId"] == inbound


async def test_an_unusable_inbound_id_is_replaced_rather_than_echoed(
    probe_client: AsyncClient,
) -> None:
    response = await probe_client.get("/probe/page", headers={REQUEST_ID_HEADER: "not a safe id"})

    assert response.headers[REQUEST_ID_HEADER] != "not a safe id"
    uuid.UUID(response.headers[REQUEST_ID_HEADER])


# ---------------------------------------------------------------------------
# 6. Optimistic locking: one machine code per resource
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("resource", sorted(CONCURRENT_MODIFICATION_CODES))
async def test_a_version_conflict_names_its_resource(
    probe_client: AsyncClient, resource: str
) -> None:
    expected_message, expected_code = CONCURRENT_MODIFICATION_CODES[resource]

    response = await probe_client.get(f"/probe/version-conflict/{resource}")

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == expected_code
    # The text is part of the contract too: the sibling backend words it the
    # same way, and a client may show it.
    assert body["message"] == expected_message


def test_the_four_conflict_codes_are_distinct() -> None:
    codes = {code for _, code in CONCURRENT_MODIFICATION_CODES.values()}

    # A shared `VERSION_CONFLICT` would leave a client that touched an order
    # and a stock level in one checkout unable to tell what to re-read.
    assert len(codes) == len(CONCURRENT_MODIFICATION_CODES)
    assert all(code.endswith("_CONCURRENT_MODIFICATION") for code in codes)


def test_a_version_conflict_is_a_conflict_by_status() -> None:
    error = VersionConflictError("Deal was modified by another request", "DEAL_X")

    assert error.status_code == 409


# ---------------------------------------------------------------------------
# 7. Enum values are UPPERCASE, in the schema and on the wire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("enum_type", [DealStage, OrderStatus, PermissionScope, StockMovementType])
def test_enum_values_are_uppercase_and_equal_their_names(
    enum_type: type[DealStage]
    | type[OrderStatus]
    | type[PermissionScope]
    | type[StockMovementType],
) -> None:
    for member in enum_type:
        assert member.value == member.value.upper()
        # Name and value are kept identical so the column, the schema and the
        # wire label can never drift apart.
        assert member.value == member.name


async def test_enums_travel_uppercase(probe_client: AsyncClient) -> None:
    data = (await probe_client.get("/probe/enums")).json()["data"]

    assert data == {"stage": "QUALIFIED", "status": "CONFIRMED", "scope": "OWN"}


def test_the_published_schema_lists_uppercase_enum_values(
    openapi_schema: dict[str, Any],
) -> None:
    """The persisted vocabularies are published exactly as the column stores them.

    Only these four are checked. A sort key or a reporting period is a wire
    vocabulary that never reaches a column, and those are spelled the way the
    reference spells them — `createdAt`, `day` — which is not uppercase.
    """
    components: dict[str, Any] = openapi_schema["components"]["schemas"]
    persisted = [DealStage, OrderStatus, PermissionScope, StockMovementType]

    for enum_type in persisted:
        published = components[enum_type.__name__]["enum"]
        assert published == [member.value for member in enum_type]
        # A single lowercase member here breaks every select in the client.
        assert all(value == value.upper() for value in published)


# ---------------------------------------------------------------------------
# 8. An `OWN` grant narrows the selection, not just the access check
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class _Result:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class RecordingSession:
    """Records the statements a service builds, and answers nothing."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result([])

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return 0


def _rendered_statements(session: RecordingSession) -> list[tuple[str, dict[str, Any]]]:
    return [
        (str(statement.compile()), dict(statement.compile().params))
        for statement in session.statements
    ]


async def _list_with_scope(scope: PermissionScope) -> RecordingSession:
    session = RecordingSession()
    service = ContactsService(cast("AsyncSession", session))
    await service.list(
        ContactAccess(actor_id=ACTOR_ID, scope=scope),
        ContactListParams(),
    )
    return session


async def test_an_own_grant_puts_the_owner_into_the_query() -> None:
    session = await _list_with_scope(PermissionScope.OWN)

    rendered = _rendered_statements(session)
    assert rendered, "the service issued no statement at all"
    for sql, params in rendered:
        # Both the page and its count are narrowed; a count taken over the
        # whole table would report other people's rows as pages that are
        # always empty.
        assert "contacts.owner_id = " in sql
        assert ACTOR_ID in params.values()


async def test_an_all_grant_does_not_narrow_the_query() -> None:
    session = await _list_with_scope(PermissionScope.ALL)

    for sql, _ in _rendered_statements(session):
        assert "contacts.owner_id = " not in sql


async def test_the_scope_reaches_the_service_untouched(
    contacts_client: AsyncClient,
    contacts_service: RecordingContactsService,
    rbac_service: Any,
) -> None:
    rbac_service.scope = PermissionScope.OWN

    response = await contacts_client.get("/api/v1/contacts")

    assert response.status_code == 200
    # The router decides nothing about visibility: it hands the breadth over,
    # because only the service can express "own records" as a predicate.
    assert contacts_service.last.access.scope is PermissionScope.OWN


# ---------------------------------------------------------------------------
# 9. A page is nested inside `data`, and every key is camelCase
# ---------------------------------------------------------------------------

CAMEL_CASE = re.compile(r"^[a-z][a-zA-Z0-9]*$")


async def test_a_page_is_wrapped_in_data(probe_client: AsyncClient) -> None:
    body = (await probe_client.get("/probe/page")).json()

    assert set(body) == {"data"}
    assert set(body["data"]) == {"items", "page", "pageSize", "total"}
    assert body["data"]["page"] == 2
    assert body["data"]["pageSize"] == 20
    assert body["data"]["total"] == 41


async def test_every_key_on_the_wire_is_camel_case(probe_client: AsyncClient) -> None:
    body = (await probe_client.get("/probe/page")).json()

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert CAMEL_CASE.match(key), f"{path}.{key} is not camelCase"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(body, "$")
    assert "displayName" in body["data"]["items"][0]


def test_no_operation_returns_a_bare_page(openapi_schema: dict[str, Any]) -> None:
    """A page must never appear as the top-level object of a response."""
    for path, method, operation in iter_operations(openapi_schema):
        for status, response in operation.get("responses", {}).items():
            content = response.get("content", {}).get("application/json")
            if content is None:
                continue
            schema = resolve_ref(openapi_schema, content.get("schema", {}))
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            if {"items", "page", "pageSize", "total"} <= set(properties):
                message = f"{method.upper()} {path} returns an unwrapped page at {status}"
                raise AssertionError(message)


def test_the_page_wrapper_publishes_camel_case_keys(openapi_schema: dict[str, Any]) -> None:
    pages = [
        schema
        for name, schema in openapi_schema["components"]["schemas"].items()
        if name.startswith("Page_") and isinstance(schema, dict)
    ]

    assert pages, "no paginated response is published at all"
    for schema in pages:
        assert "pageSize" in schema["properties"]
        assert "page_size" not in schema["properties"]


# ---------------------------------------------------------------------------
# 10. `details` is absent, not null
# ---------------------------------------------------------------------------


async def test_an_error_without_details_omits_the_key(probe_client: AsyncClient) -> None:
    body = (await probe_client.get("/probe/bare-conflict")).json()

    assert body["error"] == {"code": "CONTACT_EXISTS", "message": "Contact already exists"}
    assert "details" not in body["error"]


async def test_an_error_with_details_keeps_them(probe_client: AsyncClient) -> None:
    body = (await probe_client.post("/probe/body", json={})).json()

    assert set(body["error"]["details"]) == {"formErrors", "fieldErrors"}


def test_the_envelope_builder_never_emits_a_null_details() -> None:
    payload = error_response(status_code=404, code="NOT_FOUND", message="Not found").body

    assert b'"details"' not in payload


def test_the_published_error_schema_allows_the_key_to_be_absent(
    openapi_schema: dict[str, Any],
) -> None:
    schema = openapi_schema["components"]["schemas"]["ErrorResponse"]
    error = resolve_ref(openapi_schema, schema["properties"]["error"])

    assert "details" not in error.get("required", [])
    # The model itself must not force the key either.
    assert "details" not in ErrorResponse.model_fields


# ---------------------------------------------------------------------------
# 11. The refresh token: its format, and the cookie that carries it
# ---------------------------------------------------------------------------

REFRESH_TOKEN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.[A-Za-z0-9_-]{40,}$"
)


def _refresh_cookie(response: Response) -> SimpleCookie:
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        if REFRESH_COOKIE_NAME in cookie:
            return cookie
    message = "no refresh cookie was set"
    raise AssertionError(message)


async def test_the_refresh_token_is_a_session_id_and_a_secret(
    auth_client: AsyncClient, auth_service: FakeAuthService
) -> None:
    await auth_client.post(
        "/api/v1/auth/login", json={"email": "morgan@example.com", "password": "correct-horse"}
    )

    issued = auth_service.issued[-1]
    assert REFRESH_TOKEN.match(issued), f"the token is shaped {issued!r}"
    session_id, secret = split_refresh_token(issued)
    # The id travels in clear text so the row can be found; only the secret is
    # ever compared, and only against its stored digest.
    assert str(session_id) == issued.split(REFRESH_TOKEN_SEPARATOR)[0]
    assert secret


async def test_the_cookie_is_http_only_and_scoped_to_the_auth_endpoints(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        "/api/v1/auth/login", json={"email": "morgan@example.com", "password": "correct-horse"}
    )

    cookie = _refresh_cookie(response)[REFRESH_COOKIE_NAME]
    assert cookie["httponly"]
    # A wider or narrower path makes the browser withhold the cookie from
    # `/auth/refresh`, which the user experiences as a session that expires at
    # random.
    assert cookie["path"] == REFRESH_COOKIE_PATH
    assert cookie["samesite"].lower() == "lax"
    # Development and the test suite run over plain HTTP, where a secure
    # cookie is dropped by the browser entirely.
    assert not cookie["secure"]


async def test_the_refresh_token_never_appears_in_a_response_body(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post(
        "/api/v1/auth/login", json={"email": "morgan@example.com", "password": "correct-horse"}
    )

    assert "refreshToken" not in response.text
    assert set(response.json()["data"]) == {"user", "accessToken", "accessTokenExpiresInSeconds"}


async def test_logging_out_clears_the_cookie_on_the_same_path(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.post("/api/v1/auth/logout")

    cookie = _refresh_cookie(response)[REFRESH_COOKIE_NAME]
    assert cookie.value == ""
    # A clear on a different path leaves the old cookie in place.
    assert cookie["path"] == REFRESH_COOKIE_PATH


# ---------------------------------------------------------------------------
# 12. The address an audit entry is stamped with
# ---------------------------------------------------------------------------


async def test_the_audit_address_is_the_connection_peer(
    contacts_client: AsyncClient, contacts_service: RecordingContactsService
) -> None:
    """A forwarded header does not become the recorded address.

    The checklist reads the other way round — it expects `X-Forwarded-For` to
    win, the way Express does once `trust proxy` is set. The reference
    implementation never sets it, so its `request.ip` is the socket peer, and
    parity means doing the same. If the deployment ever gains a proxy, both
    backends have to start trusting the header on the same day; until then a
    caller must not be able to write its own address into the audit trail.
    """
    response = await contacts_client.get(
        "/api/v1/contacts", headers={"x-forwarded-for": "203.0.113.7, 198.51.100.4"}
    )

    assert response.status_code == 200
    assert contacts_service.last.access.ip_address == TRANSPORT_CLIENT_HOST


async def test_the_address_travels_into_every_write(
    contacts_client: AsyncClient, contacts_service: RecordingContactsService
) -> None:
    await contacts_client.patch(f"/api/v1/contacts/{CONTACT_ID}", json={"company": "Engines"})
    await contacts_client.delete(f"/api/v1/contacts/{CONTACT_ID}")

    # Every mutating route stamps its entry: an audit trail with holes in the
    # address column is one nobody can use for an investigation.
    for call in contacts_service.calls:
        assert call.access.ip_address == TRANSPORT_CLIENT_HOST


def test_the_address_is_carried_rather_than_derived() -> None:
    """The service is handed an address; it never looks one up itself.

    That is what keeps the decision in exactly one place — the router — so a
    change of proxy policy is a one-line change rather than a hunt through
    every module that writes to the trail.
    """
    event = AuditEvent(action="contact.updated", entity_type="contact", ip_address="203.0.113.7")

    assert event.ip_address == "203.0.113.7"
    assert AuditEvent(action="contact.deleted", entity_type="contact").ip_address is None
