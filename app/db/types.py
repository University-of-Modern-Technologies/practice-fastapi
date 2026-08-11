"""Column vocabulary shared by every model.

Declaring the physical types once keeps two properties that are easy to lose
when each model spells its own columns: identifiers are always UUIDs, timestamps
always carry a zone at millisecond precision, and money is always exact.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import Date, Integer, Numeric, String, Text, TypeDecorator, Uuid, func
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import mapped_column

#: Money is exact to the cent; floating point never touches an amount.
MONEY_PRECISION = 14
MONEY_SCALE = 2

#: Millisecond precision, with zone — the same resolution the API serialises.
TIMESTAMPTZ = TIMESTAMP(timezone=True, precision=3)

#: Applied when a model annotates a bare Python type.
TYPE_ANNOTATION_MAP: dict[Any, Any] = {
    uuid.UUID: Uuid(as_uuid=True),
    datetime: TIMESTAMPTZ,
    date: Date(),
    Decimal: Numeric(MONEY_PRECISION, MONEY_SCALE),
    dict[str, Any]: JSONB,
    str: String(255),
    int: Integer(),
}

UuidPk = Annotated[
    uuid.UUID,
    mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4),
]

UuidFk = Annotated[uuid.UUID, mapped_column(Uuid(as_uuid=True))]

CreatedAt = Annotated[
    datetime,
    mapped_column(TIMESTAMPTZ, server_default=func.now(), nullable=False),
]

UpdatedAt = Annotated[
    datetime,
    mapped_column(
        TIMESTAMPTZ,
        server_default=func.now(),
        # Maintained by the ORM as well as the server so that a write through a
        # session and a write through raw SQL both refresh it.
        onupdate=func.now(),
        nullable=False,
    ),
]

DeletedAt = Annotated[datetime | None, mapped_column(TIMESTAMPTZ, nullable=True)]

Money = Annotated[
    Decimal,
    mapped_column(Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=False),
]

#: Optimistic locking counter. Present on every model a client may update.
Version = Annotated[int, mapped_column(Integer, nullable=False, default=1, server_default="1")]

LongText = Annotated[str | None, mapped_column(Text, nullable=True)]


class InetAsText(TypeDecorator[str]):
    """PostgreSQL ``inet`` surfaced as plain text.

    The async driver decodes ``inet`` into an ``ipaddress`` object, which is
    neither what the models declare nor what the API publishes. Converting in
    one place keeps every consumer — audit entries, sessions — working with the
    string form, and keeps the column type in the schema unchanged.
    """

    impl = INET
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:  # noqa: ARG002
        return None if value is None else str(value)

    def process_result_value(self, value: object, dialect: Dialect) -> str | None:  # noqa: ARG002
        return None if value is None else str(value)


IpAddress = Annotated[str | None, mapped_column(InetAsText, nullable=True)]

Json = Annotated[dict[str, Any] | None, mapped_column(JSONB, nullable=True)]


def varchar(length: int) -> Any:
    """Shorthand for a bounded text column."""
    return String(length)
