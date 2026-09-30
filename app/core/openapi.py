"""Refusals a route declares in the published description of the API.

The generator reads a route's signature, so it knows the request and the
success body. What it cannot know is what the service underneath may refuse
with: a stale version, a missing record, a state that forbids the move. Those
answers exist only as exceptions raised somewhere below the handler, so each
route names them here, next to its path, where a reviewer sees both at once.

400 and 500 are not listed: every operation can answer them, and the factory
adds them to all of them.
"""

from __future__ import annotations

from typing import Any, Final

from app.core.responses import ErrorResponse

# The descriptions are Ukrainian and match the sibling backend word for word, so
# the Cyrillic words whose letters all look Latin stay exactly as they are.
# ruff: noqa: RUF001

__all__ = ["REFUSAL_DESCRIPTIONS", "refusals"]

REFUSAL_DESCRIPTIONS: Final[dict[int, str]] = {
    401: "Автентифікація відсутня або недійсна",
    403: "Недостатньо дозволів для операції",
    404: "Запитаний ресурс не знайдено",
    409: "Операція конфліктує з поточним станом ресурсу",
    422: "Зовнішня служба відхилила коректно сформований запит",
    502: "Зовнішня служба повернула неочікувану відповідь",
    503: "Зовнішня служба тимчасово недоступна",
    504: "Зовнішня служба не відповіла в межах таймауту",
}


def refusals(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The ``responses`` entry for the refusals a route can answer with."""
    return {
        status: {"model": ErrorResponse, "description": REFUSAL_DESCRIPTIONS[status]}
        for status in statuses
    }
