"""Declarative base.

The naming convention is not cosmetic: it makes every constraint and index name
deterministic, which is what lets migrations be reviewed as diffs and lets the
schema of this backend be compared to the sibling one mechanically.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from app.db.types import TYPE_ANNOTATION_MAP

NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """Root of the model hierarchy."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = TYPE_ANNOTATION_MAP

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"
