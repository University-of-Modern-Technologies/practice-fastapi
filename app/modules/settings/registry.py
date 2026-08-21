"""The closed set of organization settings.

The settings store is a registry, not a free-form bucket: a key exists only if
it is declared here together with the type its value must satisfy and the
default that applies while no row exists. Writing an undeclared key, or a value
of the wrong shape, is refused rather than stored — which keeps the table
readable and lets other modules depend on a value being present and well typed.

Nothing here touches the database: the registry is a pure structure, and the
service is what turns it into rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Final

from pydantic import StringConstraints, TypeAdapter, ValidationError

from app.core.errors import AppError
from app.modules.settings.types import INVALID_SETTING_VALUE, UNKNOWN_SETTING_KEY

__all__ = [
    "SETTING_KEYS",
    "SETTING_REGISTRY",
    "SettingDefinition",
    "ensure_setting_key",
    "is_setting_key",
    "parse_setting_value",
    "read_stored_value",
    "setting_default",
    "setting_definition",
]

MAX_ORGANIZATION_NAME_LENGTH = 120
MAX_ORDER_PREFIX_LENGTH = 8
MAX_WAREHOUSE_CODE_LENGTH = 32

#: Codes are folded to upper case as they are parsed, so ``eur`` and ``EUR``
#: cannot end up stored as two different settings.
CurrencyCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{3}$"),
]

OrganizationName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ORGANIZATION_NAME_LENGTH),
]

OrderNumberPrefix = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_upper=True,
        min_length=1,
        max_length=MAX_ORDER_PREFIX_LENGTH,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]

WarehouseCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_upper=True,
        min_length=1,
        max_length=MAX_WAREHOUSE_CODE_LENGTH,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]


@dataclass(frozen=True, slots=True)
class SettingDefinition[T]:
    """What one key accepts, what it means, and what it is worth by default."""

    adapter: TypeAdapter[T]
    default_value: T
    description: str


def _define[T](
    annotation: type[T] | Any, default_value: T, description: str
) -> SettingDefinition[T]:
    # The adapter is built once, at import: constructing a validator per request
    # would make every settings read pay for the declaration.
    return SettingDefinition(TypeAdapter(annotation), default_value, description)


SETTING_REGISTRY: Final[dict[str, SettingDefinition[Any]]] = {
    "organization.name": _define(
        OrganizationName,
        "Training CRM",
        "Display name of the organization.",
    ),
    "organization.defaultCurrency": _define(
        CurrencyCode,
        "USD",
        "Currency applied to new orders and deals.",
    ),
    "orders.numberPrefix": _define(
        OrderNumberPrefix,
        "ORD",
        "Prefix used when generating order numbers.",
    ),
    "warehouse.defaultCode": _define(
        WarehouseCode,
        "CENTRAL",
        "Warehouse used when a request does not name one.",
    ),
}

#: Sorted so that the listing endpoint is stable regardless of declaration order.
SETTING_KEYS: Final[tuple[str, ...]] = tuple(sorted(SETTING_REGISTRY))


def is_setting_key(key: str) -> bool:
    """Whether a string names a declared setting."""
    return key in SETTING_REGISTRY


def ensure_setting_key(key: str) -> str:
    """Narrows an arbitrary path segment to a declared key, or refuses it."""
    if not is_setting_key(key):
        raise AppError(f"Unknown setting key: {key}", 400, UNKNOWN_SETTING_KEY, {"key": key})
    return key


def setting_definition(key: str) -> SettingDefinition[Any]:
    """Declaration of a key that is already known to exist."""
    return SETTING_REGISTRY[ensure_setting_key(key)]


def setting_default(key: str) -> Any:
    return setting_definition(key).default_value


def parse_setting_value(key: str, value: Any) -> Any:
    """Validates a candidate against the type declared for its own key."""
    definition = setting_definition(key)
    try:
        return definition.adapter.validate_python(value)
    except ValidationError as error:
        raise AppError(
            f"Invalid value for setting {key}",
            400,
            INVALID_SETTING_VALUE,
            error.errors(include_url=False, include_context=False, include_input=False),
        ) from error


def read_stored_value(key: str, stored: Any) -> Any:
    """Reads a value that is already in the table.

    A row written before a declaration was tightened must not turn every read
    into a failure, so an unparsable stored value degrades to the declared
    default instead of raising.
    """
    definition = setting_definition(key)
    try:
        return definition.adapter.validate_python(stored)
    except ValidationError:
        return definition.default_value
