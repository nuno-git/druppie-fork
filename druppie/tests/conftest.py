"""Shared pytest fixtures for the druppie test suite."""

import uuid

import pytest
from sqlalchemy import String, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from druppie.db.models import Base


class SQLiteUUID(TypeDecorator):
    """Store Python uuid.UUID as a String(36) in SQLite."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
        return value


def _patch_uuid_columns_for_sqlite(base):
    """Replace PG UUID column types with a SQLite-safe decorator.

    Idempotent. Besides swapping ``col.type``, this resets each mapped
    attribute's memoized ``__clause_element__`` (an annotated clone of the
    column created at mapper-configure time). Without that reset, WHERE
    clauses built via ``Model.attr`` keep binding with the pre-swap type
    (hex-without-dashes) while inserts store dashed strings, making committed
    rows invisible to ORM lookups when other test modules configured the
    mappers first.
    """
    for table in base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, PG_UUID):
                col.type = SQLiteUUID()
            if isinstance(col.type, SQLiteUUID):
                col.__dict__.pop("comparator", None)
    for mapper in base.registry.mappers:
        for prop in mapper.column_attrs:
            comparator = getattr(mapper.class_, prop.key).comparator
            for slot in ("__clause_element__", "expressions"):
                try:
                    delattr(comparator, slot)
                except AttributeError:
                    pass


@pytest.fixture(autouse=True)
def _sqlite_uuid_columns():
    """Keep UUID columns SQLite-safe for every test in the suite."""
    _patch_uuid_columns_for_sqlite(Base)
    yield
