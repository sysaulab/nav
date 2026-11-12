"""JSON export and import for the directory tables and operator state.

Sessions and session documents are excluded by design: they are
ephemeral, per-visitor, and not part of what the operator needs to back
up. Translation jobs and their per-row progress are also excluded —
the operator re-runs the job if a restore leaves a locale incomplete.

What is included (FORMAT_VERSION 2.0):
  - directory: organization, taxonomy, location, service, contact,
    service_at_location, phone, schedule, required_document,
    service_taxonomy, live_occupancy
  - operator state: app_setting (model registry overrides, prompt
    overrides, nearby params, admin token)
  - UI dictionary: ui_string (English source) and ui_string_translation
    (every locale, including hand-edited rows with signature="manual")

The English source (ui_string) is rebuilt from code on every boot by
_sync_ui_strings, so exporting it is partly belt-and-suspenders — but a
restore that skipped it would leave ui_string_translation rows pointing
at absent FK targets. It is cleared and restored atomically with its
translations.

Format invariants:
  - format_version pins the shape. This module writes 2.0 and accepts
    1.0 (directory-only, pre-v2.0 backups) on import. Any other version
    is rejected before touching the database.
  - A 1.0 payload clears and restores only the directory tables;
    app_setting and the translation tables are left untouched.
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
    AppSetting,
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
    UiString,
    UiStringTranslation,
)


FORMAT_VERSION = "2.0"
_SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1.0", "2.0"})

# v1.0 tables, in FK-safe insert order. Every parent above its children.
# The two self-referencing tables (organization, taxonomy) are patched
# in a second pass after every row exists.
_DIRECTORY_ORDER: tuple[str, ...] = (
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

# v2.0 adds operator state. app_setting and ui_string have no FK
# dependents; ui_string_translation depends on ui_string. Insert order
# matches that dependency, so _clear_tables' reverse-of-insert ordering
# deletes children before parents.
_EXPORT_ORDER: tuple[str, ...] = _DIRECTORY_ORDER + (
    "app_setting",
    "ui_string",
    "ui_string_translation",
)

# Per-version required table set. A 1.0 payload legitimately omits the
# operator-state tables; a 2.0 payload that omits them is malformed.
_REQUIRED_BY_VERSION: dict[str, tuple[str, ...]] = {
    "1.0": _DIRECTORY_ORDER,
    "2.0": _EXPORT_ORDER,
}

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
    "app_setting": AppSetting,
    "ui_string": UiString,
    "ui_string_translation": UiStringTranslation,
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
    """Return a JSON-serializable snapshot of every persistent table.

    The name is retained for backwards compatibility with the admin
    route; the export now covers operator state (app_setting) and
    translations in addition to the directory.
    """
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
    """Return a list of validation errors. Empty list means OK.

    Accepts both 2.0 (this module's output) and 1.0 (pre-operator-state
    backups). A 1.0 payload is imported directory-only; app_setting and
    the translation tables are left untouched.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload is not a JSON object"]

    version = payload.get("format_version")
    if version not in _SUPPORTED_VERSIONS:
        errors.append(
            f"unsupported format_version: {version!r} "
            f"(supported: {sorted(_SUPPORTED_VERSIONS)})"
        )
        return errors

    tables = payload.get("tables")
    if not isinstance(tables, dict):
        errors.append("payload.tables is not an object")
        return errors

    required = _REQUIRED_BY_VERSION[version]
    allowed = set(required)

    for name in required:
        if name not in tables:
            errors.append(f"missing table: {name}")
        elif not isinstance(tables[name], list):
            errors.append(f"table {name!r} is not a list")

    for name in tables:
        if name not in allowed:
            errors.append(
                f"unknown table for format {version}: {name}"
            )
    return errors


async def _clear_tables(db: AsyncSession, table_names: set[str]) -> None:
    """Delete rows from the named tables, in reverse FK order.

    Takes the set explicitly so a v1.0 import clears only the directory
    tables it is about to restore, leaving operator state intact.

    DELETE (not TRUNCATE ... CASCADE) so we never touch session tables.
    Sessions keep running against a directory that is momentarily
    empty; the closure note in get_service_details handles any dangling
    indices from ongoing conversations.
    """
    for name in reversed(_EXPORT_ORDER):
        if name in table_names:
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
    """Load a backup snapshot. Returns per-table inserted counts.

    Wrapped in the caller's transaction — this function does NOT
    commit. A failure leaves the database unchanged.

    `mode` is currently only "replace": clear every table present in
    the payload, then insert the snapshot. A v1.0 payload clears and
    restores only the directory tables; app_setting and translations
    are left untouched. A v2.0 payload clears and restores everything.
    A future "merge" mode would upsert by id without clearing.
    """
    if mode != "replace":
        raise ValueError(f"unsupported import mode: {mode!r}")

    errors = validate_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))

    tables_to_clear = set(payload["tables"].keys())
    await _clear_tables(db, tables_to_clear)

    counts: dict[str, int] = {}
    for table_name in _EXPORT_ORDER:
        if table_name not in payload["tables"]:
            continue
        rows = payload["tables"][table_name]
        await _insert_table(db, table_name, rows)
        counts[table_name] = len(rows)

    return counts