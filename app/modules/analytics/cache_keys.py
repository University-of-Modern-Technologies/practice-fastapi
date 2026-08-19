"""Cache keys of the analytics namespace.

Module-local builders: the shared ``app.cache.keys`` only owns namespaces that
more than one module needs, so the analytics namespace lives here.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.cache.keys import cache_key, cache_key_prefix

__all__ = [
    "ANALYTICS_NAMESPACE",
    "ReportParameter",
    "analytics_prefix",
    "analytics_report_key",
]

ANALYTICS_NAMESPACE = "analytics"

#: Everything a report parameter may be once it has been normalised.
type ReportParameter = str | int | bool | None

#: Key used when a report takes no parameters at all.
_EMPTY_PARAMETERS = "all"


def _render(value: str | int | bool) -> str:
    """Renders one parameter value.

    Booleans are spelled in lower case rather than as Python repr, so a key
    written by either backend addresses the same entry.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def analytics_report_key(report: str, parameters: Mapping[str, ReportParameter]) -> str:
    """Builds a key from the normalised query parameters.

    Entries are sorted by name and absent values dropped, so two requests that
    mean the same thing map to the same key regardless of how the query string
    was ordered.
    """
    encoded = "|".join(
        f"{name}={_render(value)}"
        for name, value in sorted(parameters.items(), key=lambda entry: entry[0])
        if value is not None
    )
    return cache_key(ANALYTICS_NAMESPACE, report, encoded or _EMPTY_PARAMETERS)


def analytics_prefix() -> str:
    """Prefix covering every analytics entry, for a wholesale drop."""
    return cache_key_prefix(ANALYTICS_NAMESPACE)
