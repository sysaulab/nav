import uuid
from datetime import datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, Time, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Shared column groups ─────────────────────────────────
#
# Declared as mixins so the same three columns are not copy-pasted
# eight times. SQLAlchemy 2.0 includes Mapped columns from mixin
# classes when they are combined with Base on a concrete table.

class TimestampedMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False,
    )


class SyncableMixin:
    # (source, external_id) is the upsert key for the delta sync.
    # `source` names the feed (e.g. "c211", "211-ndp", "local").
    # `external_id` is that feed's identifier for the row.
    # `last_synced_at` is when a sync last confirmed the row is current;
    # it is NOT updated_at (which fires on any local write).
    source: Mapped[str | None] = mapped_column(String(50))
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Organization ─────────────────────────────────────────

class Organization(Base, TimestampedMixin, SyncableMixin):
    __tablename__ = "organization"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alternate_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(1024))
    legal_status: Mapped[str | None] = mapped_column(String(255))
    year_incorporated: Mapped[int | None] = mapped_column(Integer)
    logo: Mapped[str | None] = mapped_column(String(1024))
    uri: Mapped[str | None] = mapped_column(String(1024))
    tax_id: Mapped[str | None] = mapped_column(String(50))
    tax_status: Mapped[str | None] = mapped_column(String(50))
    parent_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_org_source_external"),
    )


# ── Location ─────────────────────────────────────────────
#
# `address` (flattened, human-readable) is retained for display and
# for the /api/geocode fallback. The structured fields are the HSDS
# shape and are what a real 211 sync populates; when both are present,
# `address` is the display string and the structured fields are the
# source of truth.

class Location(Base, TimestampedMixin, SyncableMixin):
    __tablename__ = "location"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="SET NULL")
    )
    name: Mapped[str | None] = mapped_column(String(255))
    alternate_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    transportation: Mapped[str | None] = mapped_column(Text)

    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    external_identifier: Mapped[str | None] = mapped_column(String(255))
    location_type: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str | None] = mapped_column(String(1024))

    # Flattened display address (retained from the pre-change schema).
    address: Mapped[str | None] = mapped_column(String(1024))

    # Structured address — HSDS Address entity, flattened onto Location
    # because a Location with multiple addresses is rare in 211 data.
    address_1: Mapped[str | None] = mapped_column(String(255))
    address_2: Mapped[str | None] = mapped_column(String(255))
    address_type: Mapped[str | None] = mapped_column(String(50))
    attention: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    region: Mapped[str | None] = mapped_column(String(255))
    state_province: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(3))

    accessibility: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        CheckConstraint("latitude IS NULL OR (latitude BETWEEN -90 AND 90)", name="ck_location_lat"),
        CheckConstraint("longitude IS NULL OR (longitude BETWEEN -180 AND 180)", name="ck_location_lng"),
        Index("ix_location_lat_lng", "latitude", "longitude"),
        UniqueConstraint("source", "external_id", name="uq_location_source_external"),
    )


# ── Service ──────────────────────────────────────────────

class Service(Base, TimestampedMixin, SyncableMixin):
    __tablename__ = "service"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alternate_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1024))
    email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    interpretation_services: Mapped[str | None] = mapped_column(String(1024))
    application_process: Mapped[str | None] = mapped_column(Text)

    fees_description: Mapped[str | None] = mapped_column(Text)
    fees: Mapped[str | None] = mapped_column(Text)
    wait_time: Mapped[str | None] = mapped_column(String(255))

    eligibility_description: Mapped[str | None] = mapped_column(Text)
    minimum_age: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    maximum_age: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    accreditations: Mapped[str | None] = mapped_column(Text)
    licenses: Mapped[str | None] = mapped_column(Text)
    taxonomy_ids: Mapped[str | None] = mapped_column(Text)

    assured_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','inactive','defunct','temporarily closed')",
            name="ck_service_status",
        ),
        UniqueConstraint("source", "external_id", name="uq_service_source_external"),
    )


# ── ServiceAtLocation ────────────────────────────────────

class ServiceAtLocation(Base, TimestampedMixin, SyncableMixin):
    __tablename__ = "service_at_location"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("location.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("service_id", "location_id", name="uq_sal_service_location"),
        UniqueConstraint("source", "external_id", name="uq_sal_source_external"),
    )


# ── Phone ────────────────────────────────────────────────
#
# HSDS Phone attaches to exactly one owner: organization, service,
# location, service_at_location, or contact. The check constraint
# enforces "at least one" — the sync worker supplies exactly the
# one the source names.

class Phone(Base, TimestampedMixin):
    __tablename__ = "phone"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(20))
    type: Mapped[str | None] = mapped_column(String(50))
    language: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="CASCADE"), index=True,
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("service.id", ondelete="CASCADE"), index=True,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("location.id", ondelete="CASCADE"), index=True,
    )
    service_at_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("service_at_location.id", ondelete="CASCADE"), index=True,
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("contact.id", ondelete="CASCADE"), index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "organization_id IS NOT NULL OR service_id IS NOT NULL OR "
            "location_id IS NOT NULL OR service_at_location_id IS NOT NULL OR "
            "contact_id IS NOT NULL",
            name="ck_phone_owner",
        ),
    )


# ── Contact ──────────────────────────────────────────────

class Contact(Base, TimestampedMixin):
    __tablename__ = "contact"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="CASCADE"), index=True,
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("service.id", ondelete="CASCADE"), index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "organization_id IS NOT NULL OR service_id IS NOT NULL",
            name="ck_contact_owner",
        ),
    )


# ── Schedule ─────────────────────────────────────────────
#
# The full HSDS Schedule carries an RRULE. That is overkill for a
# caseworker assistant: what matters is "which days, what hours",
# so `byday` uses the RRULE day notation ("MO,TU,WE,TH,FR") and
# `opens_at` / `closes_at` are plain times. `description` carries
# any free-text qualifier ("closed on statutory holidays").

class Schedule(Base, TimestampedMixin):
    __tablename__ = "schedule"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    byday: Mapped[str | None] = mapped_column(String(50))
    opens_at: Mapped[time | None] = mapped_column(Time)
    closes_at: Mapped[time | None] = mapped_column(Time)
    description: Mapped[str | None] = mapped_column(Text)

    service_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("service.id", ondelete="CASCADE"), index=True,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("location.id", ondelete="CASCADE"), index=True,
    )
    service_at_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("service_at_location.id", ondelete="CASCADE"), index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "service_id IS NOT NULL OR location_id IS NOT NULL OR "
            "service_at_location_id IS NOT NULL",
            name="ck_schedule_owner",
        ),
    )


# ── RequiredDocument ─────────────────────────────────────

class RequiredDocument(Base, TimestampedMixin):
    __tablename__ = "required_document"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    uri: Mapped[str | None] = mapped_column(String(1024))
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )


# ── Taxonomy ─────────────────────────────────────────────

class Taxonomy(Base, TimestampedMixin):
    __tablename__ = "taxonomy"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    uri: Mapped[str | None] = mapped_column(String(1024))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("taxonomy.id", ondelete="SET NULL")
    )
    parent_name: Mapped[str | None] = mapped_column(String(255))
    additional_identifiers: Mapped[str | None] = mapped_column(Text)


class ServiceTaxonomy(Base):
    __tablename__ = "service_taxonomy"

    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service.id", ondelete="CASCADE"), primary_key=True,
    )
    taxonomy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("taxonomy.id", ondelete="CASCADE"), primary_key=True,
    )


# ── Live occupancy (custom extension) ────────────────────

class LiveOccupancy(Base):
    __tablename__ = "live_occupancy"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service_at_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_at_location.id", ondelete="CASCADE"),
        nullable=False,
    )
    capacity: Mapped[int | None] = mapped_column(Integer)
    current_occupancy: Mapped[int | None] = mapped_column(Integer)
    wait_time_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )
    source: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('open','full','closed','unknown')",
            name="ck_live_occupancy_status",
        ),
        Index("ix_live_occupancy_latest", "service_at_location_id", "last_updated"),
    )


# ── Interview sessions & documents ──────────────────────

class InterviewSession(Base):
    """One ephemeral interview. Wiped on end or TTL expiry."""

    __tablename__ = "interview_session"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    postal_code: Mapped[str | None] = mapped_column(String(32))
    origin_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    origin_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    origin_display_name: Mapped[str | None] = mapped_column(String(512))
    # models.py, InterviewSession
    origin_country: Mapped[str | None] = mapped_column(String(100))
    origin_region: Mapped[str | None] = mapped_column(String(100))
    route_provider_id: Mapped[str | None] = mapped_column(String(50))

    nearby_service_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    revealed_service_indices: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active','ended','expired')", name="ck_session_status"),
        Index("ix_session_expires", "expires_at"),
    )


class SessionDocument(Base):
    """Filtered sanitizer output for one uploaded document."""

    __tablename__ = "session_document"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_session.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    route: Mapped[str | None] = mapped_column(String(50))
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pass")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    block_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    skip_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('ready','skipped_too_large','quarantine','failed')",
            name="ck_session_document_status",
        ),
    )