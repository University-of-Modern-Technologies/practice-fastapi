"""Access token extraction for the WebSocket handshake.

The token is carried by ``Sec-WebSocket-Protocol``, in one of two shapes:

* ``Sec-WebSocket-Protocol: bearer, <jwt>`` — what a browser sends when the
  socket is opened as ``new WebSocket(url, ["bearer", accessToken])``;
* ``Sec-WebSocket-Protocol: access_token.<jwt>`` — the single-value form, for
  clients that cannot send a two-element list.

Native clients that control request headers may instead send a normal
``Authorization: Bearer <jwt>`` header.

SECURITY: the query string is deliberately never consulted. A token in the URL
is written to proxy access logs, browser history and ``Referer`` headers, so it
leaks far beyond the connection it was minted for. Browsers cannot set headers
on a WebSocket handshake, which is exactly why the subprotocol is used as the
carrier — and only the marker subprotocol is ever echoed back, never the token.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

#: Marker subprotocol echoed back on a successful handshake.
BEARER_SUBPROTOCOL: Final = "bearer"

#: Prefix of the single-value subprotocol form.
ACCESS_TOKEN_SUBPROTOCOL_PREFIX: Final = "access_token."

SUBPROTOCOL_HEADER: Final = "sec-websocket-protocol"
AUTHORIZATION_HEADER: Final = "authorization"

_AUTHORIZATION_SCHEME: Final = "bearer "


def parse_subprotocols(header_value: str | None) -> list[str]:
    """Splits a ``Sec-WebSocket-Protocol`` header into its entries."""
    if not header_value:
        return []
    return [entry.strip() for entry in header_value.split(",") if entry.strip()]


def _from_authorization_header(headers: Mapping[str, str]) -> str | None:
    header = headers.get(AUTHORIZATION_HEADER)
    if not isinstance(header, str) or not header.lower().startswith(_AUTHORIZATION_SCHEME):
        return None

    token = header[len(_AUTHORIZATION_SCHEME) :].strip()
    return token or None


def _from_subprotocol_header(headers: Mapping[str, str]) -> str | None:
    protocols = parse_subprotocols(headers.get(SUBPROTOCOL_HEADER))

    for index, entry in enumerate(protocols):
        if entry.startswith(ACCESS_TOKEN_SUBPROTOCOL_PREFIX):
            token = entry[len(ACCESS_TOKEN_SUBPROTOCOL_PREFIX) :]
            if token:
                return token

        if entry.lower() == BEARER_SUBPROTOCOL and index + 1 < len(protocols):
            token = protocols[index + 1]
            if token:
                return token

    return None


def extract_access_token(headers: Mapping[str, str]) -> str | None:
    """Returns the access token offered by the handshake, or ``None``."""
    return _from_authorization_header(headers) or _from_subprotocol_header(headers)


def select_subprotocol(headers: Mapping[str, str]) -> str | None:
    """Subprotocol to accept the handshake with.

    Only the marker is echoed: replying with the token itself would put it into
    the response headers of the handshake.
    """
    protocols = parse_subprotocols(headers.get(SUBPROTOCOL_HEADER))
    lowered = {entry.lower() for entry in protocols}
    return BEARER_SUBPROTOCOL if BEARER_SUBPROTOCOL in lowered else None
