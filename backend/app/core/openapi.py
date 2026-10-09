"""What the published description of the API says beyond the signatures.

The generator reads a route's signature, so it knows the request and the
success body. What it cannot know is what the service underneath may refuse
with: a stale version, a missing record, a state that forbids the move. Those
answers exist only as exceptions raised somewhere below the handler, so each
route names them here, next to its path, where a reviewer sees both at once.

400 and 500 are not listed: every operation can answer them, and the factory
adds them to all of them.

The operation identifiers are derived here as well, by one rule that the
sibling backend applies too, so a client generated from either description
calls the same operation by the same name.
"""

from __future__ import annotations

import re
from typing import Any, Final

from fastapi.routing import APIRoute

from app.core.responses import ErrorResponse

__all__ = ["RESPONSE_DESCRIPTIONS", "operation_id", "refusals"]

_SEPARATOR_RUN = re.compile(r"[^A-Za-z0-9]+")

#: What every error status means in the description. The only place these texts
#: live; the sibling backend uses the same words.
RESPONSE_DESCRIPTIONS: Final[dict[int, str]] = {
    400: "Invalid request",
    401: "Authentication is missing or invalid",
    403: "Not enough permissions for this operation",
    404: "The requested resource was not found",
    409: "The operation conflicts with the current state of the resource",
    422: "The request is well-formed but cannot be processed",
    500: "Internal server error",
    502: "An external service returned an unexpected response",
    503: "A service is temporarily unavailable",
    504: "An external service did not respond in time",
}


def refusals(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The ``responses`` entry for the refusals a route can answer with."""
    return {
        status: {"model": ErrorResponse, "description": RESPONSE_DESCRIPTIONS[status]}
        for status in statuses
    }


def operation_id(route: APIRoute) -> str:
    """``<method>_<path>``: every run of other characters folded to one ``_``.

    ``GET /api/v1/products/{id}`` becomes ``get_api_v1_products_id``. The name
    is built from the full path, so the rule needs the route as mounted, with
    its prefix, which is the route the framework hands over here.
    """
    if not route.methods:
        message = f"Route {route.path_format} declares no HTTP method to name it by"
        raise ValueError(message)
    # One method per route is how every router here declares them; sorting
    # only keeps the name stable if a route ever carried two.
    method = sorted(route.methods)[0]
    return _SEPARATOR_RUN.sub("_", f"{method}_{route.path_format}").strip("_").lower()
