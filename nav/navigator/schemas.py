from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(_In):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class OrganizationIn(_In):
    name: str = Field(min_length=1, max_length=255)
    alternate_name: str | None = None
    description: str = ""
    email: str | None = None
    website: str | None = None
    legal_status: str | None = None
    year_incorporated: int | None = None
    logo: str | None = None
    uri: str | None = None
    parent_organization_id: UUID | None = None


class OrganizationOut(OrganizationIn, _Out):
    id: UUID
    created_at: datetime
    updated_at: datetime


class LocationIn(_In):
    organization_id: UUID | None = None
    name: str | None = None
    alternate_name: str | None = None
    description: str | None = None
    address: str | None = None
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)


class LocationOut(LocationIn, _Out):
    id: UUID
    created_at: datetime
    updated_at: datetime
    distance_deg: float | None = None


class ServiceIn(_In):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=255)
    alternate_name: str | None = None
    description: str | None = None
    url: str | None = None
    email: str | None = None
    status: str = Field(default="active", pattern="^(active|inactive|defunct|temporarily closed)$")
    interpretation_services: str | None = None
    application_process: str | None = None
    fees_description: str | None = None
    eligibility_description: str | None = None
    minimum_age: Decimal | None = Field(default=None, ge=0, le=120)
    maximum_age: Decimal | None = Field(default=None, ge=0, le=120)
    assured_date: datetime | None = None
    alert: str | None = None
    last_modified: datetime | None = None


class ServiceOut(ServiceIn, _Out):
    id: UUID
    created_at: datetime
    updated_at: datetime


class ServiceAtLocationIn(_In):
    service_id: UUID
    location_id: UUID
    description: str | None = None


class ServiceAtLocationOut(ServiceAtLocationIn, _Out):
    id: UUID
    created_at: datetime
    updated_at: datetime


class LocationServiceIn(ServiceIn):
    organization_id: UUID | None = None


class LocationServiceOut(ServiceOut):
    service_at_location_id: UUID


# ── Interview sessions, documents, chat ───────────────────

class InterviewSessionOut(_Out):
    id: UUID
    status: str
    created_at: datetime
    expires_at: datetime
    postal_code: str | None = None
    origin_display_name: str | None = None


class PostalCodeIn(_In):
    postal_code: str = Field(min_length=2, max_length=200)   # widened
    # Optional pre-resolved candidate from /api/geocode/search. When lat+lng
    # are both present the backend trusts them and skips geocoding.
    lat: Decimal | None = Field(default=None, ge=-90, le=90)
    lng: Decimal | None = Field(default=None, ge=-180, le=180)
    display_name: str | None = Field(default=None, max_length=1024)


class SessionLocationOut(_Out):
    postal_code: str | None
    origin_lat: Decimal | None
    origin_lng: Decimal | None
    origin_display_name: str | None


class DocumentMetaOut(_Out):
    id: UUID
    filename: str
    mime_type: str | None
    size_bytes: int
    route: str | None
    quality_status: str
    page_count: int
    block_count: int
    token_estimate: int
    status: str
    skip_reason: str | None
    created_at: datetime


class SkippedDocumentOut(_Out):
    id: UUID
    filename: str
    reason: str
    token_estimate: int | None = None
    remaining_budget: int | None = None


class ContextPromptOut(_Out):
    system_prompt: str
    included: list[DocumentMetaOut]
    skipped: list[SkippedDocumentOut]
    total_tokens: int
    budget_tokens: int


class ChatMessageIn(_In):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str


class ChatRequestIn(_In):
    messages: list[ChatMessageIn]