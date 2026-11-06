"""JSON export and import for the directory tables.

Sessions and session documents are excluded by design: they are
ephemeral, per-visitor, and not part of what the directory is.
The export is the directory; the sessions are the running system.

Format invariants:
  - format_version pins the shape. An import of a payload with any
    other version is rejected without touching the database.
  - Each table is a flat list of row objects. Every column of the
    corresponding model must appear in every row; an unknown column
    is an error, not silently dropped.
  - UUIDs, Decimals, datetimes, and times are strings; the decoder
    reads them back through the SQLAlchemy column type. JSON-native
    types (str, int, float, bool) pass through unchanged.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Base,
    Contact,
    LiveOccupancy,
    Location,
    Organization,
    Phone,
    RequiredDocument,
    Schedule,
    Service,
    ServiceAtLocation,
    ServiceTaxonomy,
    Taxonomy,
)


FORMAT_VERSION = "1.0"

# FK-safe insert order. Every parent appears above its children.
# The two self-referencing tables (organization, taxonomy) are patched
# in a second pass after every row exists.
_EXPORT_ORDER: tuple[str, ...] = (
    "organization",
    "taxonomy",
    "location",
    "service",
    "contact",
    "service_at_location",
    "phone",
    "schedule",
    "required_document",
    "service_taxonomy",
    "live_occupancy",
)

# table -> (parent_column, primary_key_column). Both parent columns
# are nullable, so we can insert with NULL and UPDATE afterwards.
_SELF_REFS: dict[str, tuple[str, str]] = {
    "organization": ("parent_organization_id", "id"),
    "taxonomy": ("parent_id", "id"),
}

_MODEL_BY_TABLE: dict[str, type[Base]] = {
    "organization": Organization,
    "taxonomy": Taxonomy,
    "location": Location,
    "service": Service,
    "contact": Contact,
    "service_at_location": ServiceAtLocation,
    "phone": Phone,
    "schedule": Schedule,
    "required_document": RequiredDocument,
    "service_taxonomy": ServiceTaxonomy,
    "live_occupancy": LiveOccupancy,
}


def _encode(value: Any) -> Any:
    """Serialize one column value to a JSON-safe representation."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        # String preserves precision exactly. float() would not.
        return str(value)
    if isinstance(value, datetime):
        # Naive datetimes are treated as UTC. They should not occur
        # on Postgres timestamptz, but the guard keeps the export
        # stable if the schema ever drops a timezone.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, time):
        return value.isoformat()
    return value  # str, int, float, bool, list, dict


def _decode(column_type: Any, value: Any) -> Any:
    """Reverse of _encode, driven by the SQLAlchemy column type."""
    if value is None:
        return None
    type_name = type(column_type).__name__
    if type_name == "Uuid" and isinstance(value, str):
        return uuid.UUID(value)
    if type_name == "Numeric" and isinstance(value, str):
        return Decimal(value)
    if type_name == "DateTime" and isinstance(value, str):
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if type_name == "Time" and isinstance(value, str):
        return time.fromisoformat(value)
    return value


async def export_directory(db: AsyncSession) -> dict[str, Any]:
    """Return a JSON-serializable snapshot of the directory tables."""
    out: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }
    for table_name in _EXPORT_ORDER:
        model = _MODEL_BY_TABLE[table_name]
        rows = (await db.execute(select(model))).scalars().all()
        serialized: list[dict[str, Any]] = []
        for row in rows:
            record = {
                col.name: _encode(getattr(row, col.name))
                for col in model.__table__.columns
            }
            serialized.append(record)
        out["tables"][table_name] = serialized
    return out


def validate_payload(payload: Any) -> list[str]:
    """Return a list of validation errors. Empty list means OK."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload is not a JSON object"]

    version = payload.get("format_version")
    if version != FORMAT_VERSION:
        errors.append(
            f"unsupported format_version: {version!r} "
            f"(expected {FORMAT_VERSION!r})"
        )

    tables = payload.get("tables")
    if not isinstance(tables, dict):
        errors.append("payload.tables is not an object")
        return errors

    for name in _EXPORT_ORDER:
        if name not in tables:
            errors.append(f"missing table: {name}")
        elif not isinstance(tables[name], list):
            errors.append(f"table {name!r} is not a list")

    for name in tables:
        if name not in _EXPORT_ORDER:
            errors.append(f"unknown table: {name}")
    return errors


async def _clear_directory(db: AsyncSession) -> None:
    """Delete every directory row in reverse FK order.

    DELETE (not TRUNCATE ... CASCADE) so we never touch session
    tables. Sessions keep running against a directory that is
    momentarily empty; the closure note in get_service_details
    handles any dangling indices from ongoing conversations.
    """
    for name in reversed(_EXPORT_ORDER):
        await db.execute(sa_delete(_MODEL_BY_TABLE[name]))


async def _insert_table(
    db: AsyncSession, table_name: str, rows: list[dict[str, Any]],
) -> None:
    """Insert one table's rows. Self-references are patched after flush."""
    model = _MODEL_BY_TABLE[table_name]
    self_ref = _SELF_REFS.get(table_name)
    columns_by_name = {c.name: c for c in model.__table__.columns}

    deferred: list[tuple[uuid.UUID, Any]] = []

    for raw in rows:
        record: dict[str, Any] = {}
        for name, value in raw.items():
            col = columns_by_name.get(name)
            if col is None:
                raise ValueError(
                    f"{table_name}: unknown column {name!r} in payload"
                )
            record[name] = _decode(col.type, value)

        if self_ref is not None:
            parent_col, pk_col = self_ref
            parent_value = record.get(parent_col)
            if parent_value is not None:
                deferred.append((record[pk_col], parent_value))
                record[parent_col] = None

        db.add(model(**record))

    await db.flush()

    if deferred and self_ref is not None:
        parent_col, _pk_col = self_ref
        for child_id, parent_id in deferred:
            obj = await db.get(model, child_id)
            if obj is not None:
                setattr(obj, parent_col, parent_id)


async def import_directory(
    db: AsyncSession, payload: dict[str, Any], *, mode: str = "replace",
) -> dict[str, int]:
    """Load a directory snapshot. Returns per-table inserted counts.

    Wrapped in the caller's transaction — this function does NOT
    commit. A failure leaves the database unchanged.

    `mode` is currently only "replace": clear every directory table,
    then insert the snapshot. A future "merge" mode would upsert by
    id without clearing.
    """
    if mode != "replace":
        raise ValueError(f"unsupported import mode: {mode!r}")

    errors = validate_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))

    await _clear_directory(db)

    counts: dict[str, int] = {}
    for table_name in _EXPORT_ORDER:
        rows = payload["tables"][table_name]
        await _insert_table(db, table_name, rows)
        counts[table_name] = len(rows)

    return counts