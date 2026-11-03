import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint, Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Organization(Base):
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
    parent_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="SET NULL")
    )
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class Location(Base):
    __tablename__ = "location"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="SET NULL")
    )
    name: Mapped[str | None] = mapped_column(String(255))
    alternate_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(String(1024)) 
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("latitude IS NULL OR (latitude BETWEEN -90 AND 90)", name="ck_location_lat"),
        CheckConstraint("longitude IS NULL OR (longitude BETWEEN -180 AND 180)", name="ck_location_lng"),
        # Composite index backs both bbox and radius-prefilter predicates.
        Index("ix_location_lat_lng", "latitude", "longitude"),
    )


class Service(Base):
    __tablename__ = "service"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True
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
    eligibility_description: Mapped[str | None] = mapped_column(Text)
    minimum_age: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    maximum_age: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    assured_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','inactive','defunct','temporarily closed')",
            name="ck_service_status",
        ),
    )


class ServiceAtLocation(Base):
    __tablename__ = "service_at_location"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("location.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("service_id", "location_id", name="uq_sal_service_location"),
    )


class LiveOccupancy(Base):
    """HSDS profile extension — see README of the navigator package."""

    __tablename__ = "live_occupancy"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service_at_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_at_location.id", ondelete="CASCADE"), nullable=False
    )
    capacity: Mapped[int | None] = mapped_column(Integer)
    current_occupancy: Mapped[int | None] = mapped_column(Integer)
    wait_time_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    source: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "status IN ('open','full','closed','unknown')",
            name="ck_live_occupancy_status",
        ),
        Index("ix_live_occupancy_latest", "service_at_location_id", "last_updated"),
    )

    # ── Interview sessions & uploaded documents ────────────────

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

    # Origin used to localize services for every chat turn. Set once via
    # POST /interviews/{sid}/location; chat and finalize refuse to run without it.
    postal_code: Mapped[str | None] = mapped_column(String(32))
    origin_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    origin_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    origin_display_name: Mapped[str | None] = mapped_column(String(512))
    
    # Stable index built at set_location time. entries are stringified UUIDs;
    # the LLM addresses them positionally ("[07]"). Reset with
    # revealed_service_indices on every location change so indices never drift.
    nearby_service_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    revealed_service_indices: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('active','ended','expired')", name="ck_session_status"),
        Index("ix_session_expires", "expires_at"),
    )


class SessionDocument(Base):
    """Filtered sanitizer output for one uploaded document.

    No binary is ever stored — the sanitizer is the sole extractor, and we
    keep only the pages/blocks we intend to inject into the system prompt.
    """

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