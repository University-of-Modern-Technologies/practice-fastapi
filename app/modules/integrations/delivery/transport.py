"""The seam between the delivery client and the outside world.

Everything the client does — retries, backoff, the circuit breaker, response
validation — is expressed in terms of this port. Production wires the HTTP
transport, the default configuration wires the in-repo stub, and tests wire a
hand-written fake. No layer above ever learns which one is in use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.modules.integrations.types import TransportKind

if TYPE_CHECKING:  # pragma: no cover - import used for typing only
    import httpx

__all__ = [
    "DeliveryTransport",
    "DeliveryTransportRequest",
    "DeliveryTransportResponse",
    "HttpDeliveryTransport",
    "TransportTimeoutError",
]


class TransportTimeoutError(Exception):
    """Raised by a transport when the per-attempt deadline expires.

    The client has to tell "the dependency was too slow" from "the socket
    broke", and it must do so without importing an HTTP library: only the
    transport knows which exception its client raises, so it translates it here.
    """


#: Last-resort deadline for a caller that supplied none; see ``timeout_ms``.
DEFAULT_FALLBACK_TIMEOUT_MS = 30_000.0


@dataclass(frozen=True, slots=True)
class DeliveryTransportRequest:
    """One attempt against the upstream."""

    method: Literal["GET", "POST"]
    #: Path relative to the upstream base URL, always starting with a slash.
    path: str
    #: Per-attempt deadline; the transport must abort when it fires. The retry
    #: layer overwrites this with its configured value on every attempt, so in
    #: practice the default is never observed. It is a real duration rather
    #: than zero because zero would make httpx give up before the connection is
    #: even open, turning a forgotten deadline into an upstream that looks
    #: permanently down.
    timeout_ms: float = DEFAULT_FALLBACK_TIMEOUT_MS
    #: ``None`` means the request carries no body at all.
    body: Any = None
    #: Only idempotent calls are retried. Replaying a shipment creation after a
    #: timeout could hand the customer two parcels, so a non-idempotent call is
    #: sent once and its failure is reported honestly. Leaf transports ignore
    #: this field; it exists for the retry layer.
    idempotent: bool = True


@dataclass(frozen=True, slots=True)
class DeliveryTransportResponse:
    """What came back, reduced to the three things the client reads."""

    status: int
    #: Lower-cased header names. Only the headers the client reads are needed.
    headers: dict[str, str]
    #: Parsed JSON payload, or ``None`` when the body was empty or not JSON.
    body: Any


class DeliveryTransport(Protocol):
    """Anything that can carry one delivery request to somewhere and back."""

    #: Labels the transport in the health endpoint.
    kind: TransportKind

    async def send(self, request: DeliveryTransportRequest) -> DeliveryTransportResponse: ...


# Only the headers the retry logic actually inspects are carried across the
# seam, so nothing sensitive from the upstream response can leak by accident.
FORWARDED_HEADERS = ("retry-after", "content-type")


class HttpDeliveryTransport:
    """Talks to a real provider over HTTP."""

    kind: TransportKind = TransportKind.HTTP

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    def _ensure_client(self) -> httpx.AsyncClient:
        """Builds the HTTP client on first use.

        The import is deferred so that importing this module — which the
        application does at startup, whatever transport is configured — never
        depends on an HTTP library being installed.
        """
        if self._client is None:
            import httpx  # noqa: PLC0415

            self._client = httpx.AsyncClient()
        return self._client

    async def send(self, request: DeliveryTransportRequest) -> DeliveryTransportResponse:
        # Deferred for the same reason as in ``_ensure_client``.
        import httpx  # noqa: PLC0415

        client = self._ensure_client()
        headers = {"accept": "application/json"}
        if self._api_key is not None:
            headers["authorization"] = f"Bearer {self._api_key}"
        if request.body is not None:
            headers["content-type"] = "application/json"

        try:
            response = await client.request(
                request.method,
                f"{self._base_url}{request.path}",
                headers=headers,
                timeout=request.timeout_ms / 1000.0,
                **({} if request.body is None else {"json": request.body}),
            )
        except httpx.TimeoutException as error:
            message = "The delivery request exceeded its deadline"
            raise TransportTimeoutError(message) from error

        return DeliveryTransportResponse(
            status=response.status_code,
            headers=_read_headers(response),
            body=_read_body(response),
        )

    async def aclose(self) -> None:
        """Releases the connection pool, if this transport opened one."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


def _read_headers(response: httpx.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name in FORWARDED_HEADERS:
        value = response.headers.get(name)
        if value is not None:
            headers[name] = value
    return headers


def _read_body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        # A non-JSON body is not an error here: the client's validation turns it
        # into a controlled DELIVERY_INVALID_RESPONSE further up.
        return None
