from __future__ import annotations

import hmac
import json
import logging
import math
import urllib.parse
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import (
    and_, delete as sa_delete, func, select, text, update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.base import ModelSpec
from ..ai.registry import get_registry, reload_registry
from ..config import Settings
from ..db import get_db
from ..models import (
    AppSetting, Location, Organization, Phone, Service, ServiceAtLocation,
    TranslationJob, UiString, UiStringTranslation,
)
from ..schemas import (
    LocationIn, LocationOut, LocationServiceIn, OrganizationIn, OrganizationOut,
    ServiceIn, ServiceOut,
)
from ..settings_store import delete_app_setting, set_app_setting
from ..backup import export_directory, import_directory
from ..runtime import (
    KEY_ADMIN_TOKEN, KEY_CHAT_PROMPT, KEY_FINALIZE_PROMPT, KEY_NEARBY,
    defaults_for, get_runtime, reload_runtime,
)
from datetime import datetime, timezone

log = logging.getLogger("navigator.admin")

router = APIRouter(prefix="/admin-api", tags=["admin"])

_settings: Settings | None = None


def bind_settings(settings: Settings) -> None:
    global _settings
    _settings = settings


def _cfg() -> Settings:
    assert _settings is not None, "bind_settings() not called"
    return _settings


async def require_admin(
    authorization: str | None = Header(default=None),
) -> None:
    # Effective token = DB override if present, else env. Runtime holds
    # the effective value; see navigator/runtime.py.
    effective = get_runtime().current().admin_token
    if not effective:
        raise HTTPException(503, "admin is not configured on this server")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token.encode(), effective.encode()):
        raise HTTPException(401, "invalid admin token")


# ── phone schemas ────────────────────────────────────────

class PhoneIn(BaseModel):
    number: str = Field(min_length=1, max_length=50)
    type: str | None = Field(default=None, max_length=50)
    extension: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=50)
    description: str | None = None


class PhoneOut(BaseModel):
    id: str
    number: str
    type: str | None
    extension: str | None
    language: str | None
    description: str | None

    @classmethod
    def from_orm(cls, p: Phone) -> "PhoneOut":
        return cls(
            id=str(p.id), number=p.number, type=p.type,
            extension=p.extension, language=p.language, description=p.description,
        )


async def _fetch_phones(
    db: AsyncSession, field: str, owner_ids: list[UUID],
) -> dict[UUID, list[PhoneOut]]:
    if not owner_ids:
        return {}
    col = getattr(Phone, field)
    stmt = select(Phone).where(col.in_(owner_ids)).order_by(Phone.number)
    rows = (await db.execute(stmt)).scalars().all()
    out: dict[UUID, list[PhoneOut]] = {}
    for r in rows:
        oid = getattr(r, field)
        out.setdefault(oid, []).append(PhoneOut.from_orm(r))
    return out


# ── health ───────────────────────────────────────────────

@router.get("/health", dependencies=[Depends(require_admin)])
async def admin_health() -> dict[str, Any]:
    reg = get_registry()
    return {
        "ok": True,
        "models": len(reg.all()),
        "default_chat": reg.default_chat_id(),
        "default_finalize": reg.default_finalize_id(),
    }


# ── models ───────────────────────────────────────────────

class ModelIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    module: str = Field(pattern="^(ollama|openai)$")
    endpoint: str = Field(min_length=1, max_length=1024)
    model: str = Field(min_length=1, max_length=255)
    context_window: int = Field(gt=0, le=10_000_000)
    max_output_tokens: int = Field(gt=0)
    label: str = Field(default="", max_length=255)
    api_key_env: str | None = None
    enabled: bool = True


@router.get("/models", dependencies=[Depends(require_admin)])
async def list_models() -> list[dict[str, Any]]:
    return [s.to_dict() for s in get_registry().all()]


@router.get("/models/defaults", dependencies=[Depends(require_admin)])
async def get_defaults() -> dict[str, str]:
    reg = get_registry()
    return {
        "chat": reg.default_chat_id(),
        "finalize": reg.default_finalize_id(),
        "translate": reg.default_translate_id(),
    }


class DefaultsIn(BaseModel):
    chat: str | None = None
    finalize: str | None = None
    translate: str | None = None


@router.put("/models/defaults", dependencies=[Depends(require_admin)])
async def set_defaults(
    payload: DefaultsIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    reg = get_registry()
    if payload.chat is not None:
        if reg.get(payload.chat) is None:
            raise HTTPException(400, f"unknown model id: {payload.chat!r}")
        await set_app_setting(db, "default.chat", payload.chat)
    if payload.finalize is not None:
        if reg.get(payload.finalize) is None:
            raise HTTPException(400, f"unknown model id: {payload.finalize!r}")
        await set_app_setting(db, "default.finalize", payload.finalize)
    if payload.translate is not None:
        if reg.get(payload.translate) is None:
            raise HTTPException(400, f"unknown model id: {payload.translate!r}")
        await set_app_setting(db, "default.translate", payload.translate)

    reg = await reload_registry(db, _cfg())
    return {
        "chat": reg.default_chat_id(),
        "finalize": reg.default_finalize_id(),
        "translate": reg.default_translate_id(),
    }


@router.get("/models/{model_id}", dependencies=[Depends(require_admin)])
async def get_model(model_id: str) -> dict[str, Any]:
    spec = get_registry().get(model_id)
    if spec is None:
        raise HTTPException(404, "model not found")
    return spec.to_dict()


@router.put("/models/{model_id}", dependencies=[Depends(require_admin)])
async def put_model(
    model_id: str,
    payload: ModelIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if model_id != payload.id:
        raise HTTPException(400, "path id and body id must match")
    if payload.max_output_tokens >= payload.context_window:
        raise HTTPException(
            400, "max_output_tokens must be smaller than context_window",
        )
    await set_app_setting(db, f"model.{model_id}", payload.model_dump())
    reg = await reload_registry(db, _cfg())
    spec = reg.get(model_id)
    if spec is None:
        raise HTTPException(500, "model not present after write")
    return spec.to_dict()


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_model(model_id: str, db: AsyncSession = Depends(get_db)) -> None:
    reg = get_registry()
    if reg.default_chat_id() == model_id or reg.default_finalize_id() == model_id:
        raise HTTPException(
            409,
            f"cannot delete {model_id!r}: it is currently a default. "
            "Set a different default first.",
        )
    deleted = await delete_app_setting(db, f"model.{model_id}")
    if not deleted:
        raise HTTPException(404, "model not found (no DB override)")
    await reload_registry(db, _cfg())

# ── admin token ──────────────────────────────────────────

class TokenStatusOut(BaseModel):
    configured: bool
    source: str                     # "env" | "database" | "none"


@router.get("/auth/status", dependencies=[Depends(require_admin)])
async def token_status(db: AsyncSession = Depends(get_db)) -> TokenStatusOut:
    effective = get_runtime().current().admin_token
    if not effective:
        return TokenStatusOut(configured=False, source="none")
    # Mirror runtime.load()'s override detection: a non-empty DB value
    # that parses to a non-empty string means the operator has set a
    # custom token via this console.
    row = await db.get(AppSetting, KEY_ADMIN_TOKEN)
    has_override = False
    if row is not None and row.value.strip():
        try:
            v = json.loads(row.value)
            if isinstance(v, str) and v:
                has_override = True
        except json.JSONDecodeError:
            has_override = True
    return TokenStatusOut(
        configured=True,
        source="database" if has_override else "env",
    )


class ChangeTokenIn(BaseModel):
    current_token: str = Field(min_length=1)
    new_token: str = Field(min_length=16)
    confirm_token: str = Field(min_length=16)


@router.put("/auth/token", dependencies=[Depends(require_admin)])
async def change_admin_token(
    payload: ChangeTokenIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    effective = get_runtime().current().admin_token
    if not effective:
        # Unreachable: require_admin 503s first. Kept as belt-and-suspenders
        # so a future refactor can't silently allow token reset on an
        # unconfigured server.
        raise HTTPException(503, "admin is not configured on this server")

    if not hmac.compare_digest(
        payload.current_token.encode(), effective.encode(),
    ):
        raise HTTPException(401, "current token is incorrect")

    if payload.new_token != payload.confirm_token:
        raise HTTPException(400, "new_token and confirm_token do not match")

    if hmac.compare_digest(
        payload.new_token.encode(), effective.encode(),
    ):
        raise HTTPException(400, "new token is identical to current")

    await set_app_setting(db, KEY_ADMIN_TOKEN, payload.new_token)

    # The DB write committed above. If reload fails between here and
    # return, the DB has the new token but the runtime still validates
    # against the old one — a lockout once the client updates its
    # sessionStorage. Surface this loudly: the operator needs to
    # restart, then log in with the new token.
    try:
        await reload_runtime(db, _cfg())
    except Exception as e:
        log.exception("auth.token_reload_failed err=%s", e)
        raise HTTPException(
            500,
            "Token was saved to the database but the runtime failed to "
            "reload. Restart the server to apply it, then sign in with "
            "the new token. Detail: " + str(e),
        )

    return {"ok": True}

# ── geocoding proxy ──────────────────────────────────────

@router.get("/geocode/search", dependencies=[Depends(require_admin)])
async def admin_geocode_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(5, ge=1, le=10),
) -> list[dict[str, Any]]:
    endpoint = _cfg().photon_endpoint.rstrip("/")
    params = urllib.parse.urlencode({"q": q, "limit": limit, "lang": "en"})
    
    import httpx
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{endpoint}/api?{params}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"photon unreachable: {e}")
        
    if r.status_code >= 400:
        raise HTTPException(502, f"photon returned {r.status_code}")

    try:
        data = r.json()
    except ValueError as e:
        raise HTTPException(502, f"photon returned non-JSON: {e}")

    from ..geocode import photon_display_name
    out = []
    for feat in data.get("features", [])[:limit]:
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        try:
            lon, lat = float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            continue

        display_name = photon_display_name(props)
        if not display_name:
            continue

        out.append({
            "lat": lat,
            "lng": lon,
            "display_name": display_name,
            "postcode": props.get("postcode"),
            "city": props.get("city"),
        })
    return out


# ── prompt & nearby parameters ───────────────────────────

class PromptStateOut(BaseModel):
    chat_prompt: str
    finalize_prompt: str
    nearby: dict[str, Any]
    defaults: dict[str, Any]
    overridden: dict[str, bool]


@router.get("/prompt", dependencies=[Depends(require_admin)])
async def get_prompt_state(
    db: AsyncSession = Depends(get_db),
) -> PromptStateOut:
    rt = get_runtime().current()
    d = defaults_for(_cfg())

    rows = (await db.execute(
        select(AppSetting).where(
            AppSetting.key.in_(
                [KEY_CHAT_PROMPT, KEY_FINALIZE_PROMPT, KEY_NEARBY]
            )
        )
    )).scalars().all()
    present = {r.key for r in rows}

    return PromptStateOut(
        chat_prompt=rt.chat_prompt,
        finalize_prompt=rt.finalize_prompt,
        nearby=rt.nearby.to_dict(),
        defaults={
            "chat_prompt": d.chat_prompt,
            "finalize_prompt": d.finalize_prompt,
            "nearby": d.nearby.to_dict(),
        },
        overridden={
            "chat": KEY_CHAT_PROMPT in present,
            "finalize": KEY_FINALIZE_PROMPT in present,
            "nearby": KEY_NEARBY in present,
        },
    )


class PromptTextIn(BaseModel):
    text: str = Field(min_length=1)


@router.put("/prompt/chat", dependencies=[Depends(require_admin)])
async def put_chat_prompt(
    payload: PromptTextIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await set_app_setting(db, KEY_CHAT_PROMPT, payload.text)
    await reload_runtime(db, _cfg())
    return {"ok": True}


@router.put("/prompt/finalize", dependencies=[Depends(require_admin)])
async def put_finalize_prompt(
    payload: PromptTextIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await set_app_setting(db, KEY_FINALIZE_PROMPT, payload.text)
    await reload_runtime(db, _cfg())
    return {"ok": True}


class NearbyIn(BaseModel):
    radius_km: float = Field(gt=0, le=1000)
    location_limit: int = Field(gt=0, le=500)
    index_limit: int = Field(gt=0, le=2000)


@router.put("/prompt/nearby", dependencies=[Depends(require_admin)])
async def put_nearby(
    payload: NearbyIn,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if payload.location_limit > payload.index_limit:
        raise HTTPException(
            400,
            "location_limit must be <= index_limit "
            "(location_limit is the number of places; index_limit is "
            "the number of services drawn from them)",
        )
    await set_app_setting(db, KEY_NEARBY, payload.model_dump())
    await reload_runtime(db, _cfg())
    return {"ok": True}


@router.delete(
    "/prompt/{section}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def reset_prompt_section(
    section: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    key = {
        "chat": KEY_CHAT_PROMPT,
        "finalize": KEY_FINALIZE_PROMPT,
        "nearby": KEY_NEARBY,
    }.get(section)
    if key is None:
        raise HTTPException(404, f"unknown section: {section!r}")
    await delete_app_setting(db, key)
    await reload_runtime(db, _cfg())

# ── directory: organizations ─────────────────────────────

class AdminOrgOut(OrganizationOut):
    phones: list[PhoneOut] = []

class OrganizationsPage(BaseModel):
    items: list[AdminOrgOut]
    total: int
    page: int
    page_size: int


@router.get("/organizations", dependencies=[Depends(require_admin)])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> OrganizationsPage:
    total = (await db.execute(
        select(func.count()).select_from(Organization)
    )).scalar() or 0

    rows = (await db.execute(
        select(Organization)
        .order_by(Organization.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    phones_map = await _fetch_phones(db, "organization_id", [r.id for r in rows])

    items = []
    for org in rows:
        item = AdminOrgOut.model_validate(org)
        item.phones = phones_map.get(org.id, [])
        items.append(item)

    return OrganizationsPage(
        items=items,
        total=total, page=page, page_size=page_size,
    )


@router.post("/organizations", response_model=OrganizationOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_organization(payload: OrganizationIn, db: AsyncSession = Depends(get_db)) -> OrganizationOut:
    org = Organization(**payload.model_dump())
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return OrganizationOut.model_validate(org)


@router.put("/organizations/{org_id}", response_model=OrganizationOut, dependencies=[Depends(require_admin)])
async def update_organization(org_id: UUID, payload: OrganizationIn, db: AsyncSession = Depends(get_db)) -> OrganizationOut:
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "organization not found")
    for k, v in payload.model_dump().items():
        setattr(org, k, v)
    await db.commit()
    await db.refresh(org)
    return OrganizationOut.model_validate(org)


@router.delete("/organizations/{org_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_organization(org_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "organization not found")

    loc_ids = (await db.execute(select(Location.id).where(Location.organization_id == org_id))).scalars().all()
    svc_ids = (await db.execute(select(Service.id).where(Service.organization_id == org_id))).scalars().all()
    
    if loc_ids:
        await db.execute(sa_delete(ServiceAtLocation).where(ServiceAtLocation.location_id.in_(loc_ids)))
        await db.execute(sa_delete(Location).where(Location.id.in_(loc_ids)))
    if svc_ids:
        await db.execute(sa_delete(ServiceAtLocation).where(ServiceAtLocation.service_id.in_(svc_ids)))
        await db.execute(sa_delete(Service).where(Service.id.in_(svc_ids)))
        
    await db.delete(org)
    await db.commit()


# ── directory: locations ─────────────────────────────────

class AdminLocOut(LocationOut):
    phones: list[PhoneOut] = []

class LocationWithCount(BaseModel):
    id: str
    name: str | None
    alternate_name: str | None
    description: str | None
    address: str | None
    latitude: str | None
    longitude: str | None
    service_count: int
    phones: list[PhoneOut] = []


@router.get("/organizations/{org_id}/locations", response_model=list[LocationWithCount], dependencies=[Depends(require_admin)])
async def list_org_locations(org_id: UUID, db: AsyncSession = Depends(get_db)) -> list[LocationWithCount]:
    if not await db.get(Organization, org_id):
        raise HTTPException(404, "organization not found")

    stmt = (
        select(
            Location.id, Location.name, Location.alternate_name, Location.description,
            Location.address, Location.latitude, Location.longitude,
            func.count(ServiceAtLocation.id).label("svc_count"),
        )
        .outerjoin(ServiceAtLocation, ServiceAtLocation.location_id == Location.id)
        .where(Location.organization_id == org_id)
        .group_by(Location.id)
        .order_by(Location.name.nulls_last(), Location.id)
    )
    rows = (await db.execute(stmt)).all()
    phones_map = await _fetch_phones(db, "location_id", [r.id for r in rows])

    return [
        LocationWithCount(
            id=str(r.id),
            name=r.name,
            alternate_name=r.alternate_name,
            description=r.description,
            address=r.address,
            latitude=str(r.latitude) if r.latitude is not None else None,
            longitude=str(r.longitude) if r.longitude is not None else None,
            service_count=int(r.svc_count),
            phones=phones_map.get(r.id, []),
        )
        for r in rows
    ]

# ── flat location search ─────────────────────────────────

class OrgOption(BaseModel):
    id: str
    name: str


@router.get("/organizations/options", dependencies=[Depends(require_admin)])
async def organization_options(db: AsyncSession = Depends(get_db)) -> list[OrgOption]:
    rows = (await db.execute(
        select(Organization.id, Organization.name).order_by(Organization.name)
    )).all()
    return [OrgOption(id=str(r.id), name=r.name) for r in rows]


class LocationAdminRow(BaseModel):
    id: str
    name: str | None
    alternate_name: str | None
    description: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    organization_id: str | None
    organization_name: str | None
    service_count: int
    distance_km: float | None = None


class LocationsPage(BaseModel):
    items: list[LocationAdminRow]
    total: int
    page: int
    page_size: int


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@router.get("/locations", dependencies=[Depends(require_admin)])
async def search_locations(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="Partial match on name or alternate name"),
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    radius_km: float | None = Query(
        None,
        gt=0,
        le=1000,
        description="Optional max distance (km) from lat/lng. Omit to sort by distance.",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> LocationsPage:
    if (lat is None) != (lng is None):
        raise HTTPException(400, "lat and lng must be provided together")
    if radius_km is not None and lat is None:
        raise HTTPException(400, "radius_km requires lat and lng")

    base = (
        select(
            Location,
            Organization.name.label("org_name"),
            func.count(ServiceAtLocation.id).label("svc_count"),
        )
        .outerjoin(Organization, Organization.id == Location.organization_id)
        .outerjoin(ServiceAtLocation, ServiceAtLocation.location_id == Location.id)
        .group_by(Location.id, Organization.name)
    )

    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.where(
            Location.name.ilike(like)
            | Location.alternate_name.ilike(like)
        )

    # ── Distance mode ──────────────────────────────────────────
    #
    # NULL coordinates mean the location is a global service (a crisis
    # line, a province-wide program, an info number). It applies to
    # every customer regardless of address, so it ranks first — it is
    # NOT a coordinate-less anomaly to be hidden.
    #
    # Rows are partitioned into globals (NULL coords) and locals (coords
    # present). Globals are sorted by name for stable ordering; locals
    # are sorted by distance with name as a stable tiebreak. Concatenated
    # for pagination: globals, then locals.
    if lat is not None and lng is not None:
        if radius_km is not None:
            pad_lat = radius_km / 111.0
            cos_lat = max(math.cos(math.radians(lat)), 0.01)
            pad_lng = pad_lat / cos_lat
            base = base.where(
                Location.latitude.between(lat - pad_lat, lat + pad_lat),
                Location.longitude.between(lng - pad_lng, lng + pad_lng),
            )

        rows = (await db.execute(base)).all()
        globals_list: list[tuple[Any, Any, int]] = []
        locals_list: list[tuple[Any, Any, int, float]] = []

        for loc, org_name, svc_count in rows:
            if loc.latitude is None or loc.longitude is None:
                globals_list.append((loc, org_name, int(svc_count)))
                continue
            d = _haversine_km(lat, lng, float(loc.latitude), float(loc.longitude))
            if radius_km is not None and d > radius_km:
                continue
            locals_list.append((loc, org_name, int(svc_count), d))

        globals_list.sort(key=lambda x: (x[0].name or "").lower())
        locals_list.sort(key=lambda x: (x[3], (x[0].name or "").lower()))

        combined: list[tuple[Any, Any, int, float | None]] = [
            (loc, org_name, sc, None) for loc, org_name, sc in globals_list
        ] + locals_list

        total = len(combined)
        start = (page - 1) * page_size
        items = [
            LocationAdminRow(
                id=str(loc.id), name=loc.name,
                alternate_name=loc.alternate_name, description=loc.description,
                address=loc.address,
                latitude=float(loc.latitude) if loc.latitude is not None else None,
                longitude=float(loc.longitude) if loc.longitude is not None else None,
                organization_id=str(loc.organization_id) if loc.organization_id else None,
                organization_name=org_name,
                service_count=sc,
                distance_km=round(d, 2) if d is not None else None,
            )
            for loc, org_name, sc, d in combined[start:start + page_size]
        ]
        return LocationsPage(items=items, total=total, page=page, page_size=page_size)

    # ── Alphabetical mode (no origin) ──────────────────────────
    #
    # Unchanged. Globals are mixed in by name; they're not ranked first
    # here because the user explicitly asked for alphabetical order.
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0
    rows = (await db.execute(
        base.order_by(Location.name.nulls_last(), Location.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()
    items = [
        LocationAdminRow(
            id=str(loc.id), name=loc.name,
            alternate_name=loc.alternate_name, description=loc.description,
            address=loc.address,
            latitude=float(loc.latitude) if loc.latitude is not None else None,
            longitude=float(loc.longitude) if loc.longitude is not None else None,
            organization_id=str(loc.organization_id) if loc.organization_id else None,
            organization_name=org_name,
            service_count=int(svc_count),
        )
        for loc, org_name, svc_count in rows
    ]
    return LocationsPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/locations/{loc_id}", response_model=LocationOut, dependencies=[Depends(require_admin)])
async def get_location(loc_id: UUID, db: AsyncSession = Depends(get_db)) -> LocationOut:
    loc = await db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "location not found")
    return LocationOut.model_validate(loc)


@router.post("/locations", response_model=LocationOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_location_global(payload: LocationIn, db: AsyncSession = Depends(get_db)) -> LocationOut:
    if payload.organization_id is None:
        raise HTTPException(400, "organization_id is required")
    if await db.get(Organization, payload.organization_id) is None:
        raise HTTPException(400, f"organization {payload.organization_id} does not exist")
    loc = Location(**payload.model_dump())
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return LocationOut.model_validate(loc)





@router.post("/organizations/{org_id}/locations", response_model=LocationOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_location(org_id: UUID, payload: LocationIn, db: AsyncSession = Depends(get_db)) -> LocationOut:
    if not await db.get(Organization, org_id):
        raise HTTPException(404, "organization not found")
    
    data = payload.model_dump(exclude={"organization_id"})
    loc = Location(**data, organization_id=org_id)
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return LocationOut.model_validate(loc)


@router.put("/locations/{loc_id}", response_model=LocationOut, dependencies=[Depends(require_admin)])
async def update_location(loc_id: UUID, payload: LocationIn, db: AsyncSession = Depends(get_db)) -> LocationOut:
    loc = await db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "location not found")

    # Reallocating the org moves every service at this location with it.
    # Leaving services under the old org would break the tree UI, which
    # assumes services at a location belong to the location's org.
    new_org_id = payload.organization_id
    if new_org_id is not None and new_org_id != loc.organization_id:
        if await db.get(Organization, new_org_id) is None:
            raise HTTPException(400, f"organization {new_org_id} does not exist")
        svc_ids = (await db.execute(
            select(ServiceAtLocation.service_id).where(ServiceAtLocation.location_id == loc_id)
        )).scalars().all()
        if svc_ids:
            await db.execute(
                update(Service)
                .where(Service.id.in_(svc_ids))
                .values(organization_id=new_org_id)
            )
        loc.organization_id = new_org_id

    for k, v in payload.model_dump().items():
        if k != "organization_id":
            setattr(loc, k, v)
    await db.commit()
    await db.refresh(loc)
    return LocationOut.model_validate(loc)


@router.delete("/locations/{loc_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_location(loc_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    loc = await db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "location not found")

    sal_svc_ids = (await db.execute(select(ServiceAtLocation.service_id).where(ServiceAtLocation.location_id == loc_id))).scalars().all()
    
    if sal_svc_ids:
        await db.execute(sa_delete(ServiceAtLocation).where(ServiceAtLocation.service_id.in_(sal_svc_ids)))
        await db.execute(sa_delete(Service).where(Service.id.in_(sal_svc_ids)))

    await db.delete(loc)
    await db.commit()


# ── directory: services ──────────────────────────────────

class AdminSvcOut(ServiceOut):
    phones: list[PhoneOut] = []


@router.get("/locations/{loc_id}/services", response_model=list[AdminSvcOut], dependencies=[Depends(require_admin)])
async def list_loc_services(loc_id: UUID, db: AsyncSession = Depends(get_db)) -> list[AdminSvcOut]:
    if not await db.get(Location, loc_id):
        raise HTTPException(404, "location not found")

    stmt = (
        select(Service)
        .join(ServiceAtLocation, ServiceAtLocation.service_id == Service.id)
        .where(ServiceAtLocation.location_id == loc_id)
        .order_by(Service.name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    
    phones_map = await _fetch_phones(db, "service_id", [r.id for r in rows])

    items = []
    for svc in rows:
        item = AdminSvcOut.model_validate(svc)
        item.phones = phones_map.get(svc.id, [])
        items.append(item)

    return items


@router.post("/locations/{loc_id}/services", response_model=ServiceOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_service(loc_id: UUID, payload: LocationServiceIn, db: AsyncSession = Depends(get_db)) -> ServiceOut:
    loc = await db.get(Location, loc_id)
    if not loc or not loc.organization_id:
        raise HTTPException(400, "location not found or has no organization")

    data = payload.model_dump(exclude={"organization_id"})
    svc = Service(**data, organization_id=loc.organization_id)
    db.add(svc)
    await db.flush()

    sal = ServiceAtLocation(service_id=svc.id, location_id=loc.id)
    db.add(sal)
    await db.commit()
    await db.refresh(svc)
    return ServiceOut.model_validate(svc)


@router.put("/services/{svc_id}", response_model=ServiceOut, dependencies=[Depends(require_admin)])
async def update_service(svc_id: UUID, payload: LocationServiceIn, db: AsyncSession = Depends(get_db)) -> ServiceOut:
    svc = await db.get(Service, svc_id)
    if not svc:
        raise HTTPException(404, "service not found")
    
    data = payload.model_dump(exclude={"organization_id"})
    for k, v in data.items():
        setattr(svc, k, v)
        
    await db.commit()
    await db.refresh(svc)
    return ServiceOut.model_validate(svc)


@router.delete("/services/{svc_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_service(svc_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    svc = await db.get(Service, svc_id)
    if not svc:
        raise HTTPException(404, "service not found")
    await db.delete(svc)
    await db.commit()


# ── directory: phones ────────────────────────────────────

@router.post("/phones/{owner_type}/{owner_id}", response_model=PhoneOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_phone(owner_type: str, owner_id: UUID, payload: PhoneIn, db: AsyncSession = Depends(get_db)) -> PhoneOut:
    kwargs = {}
    if owner_type == "org":
        if not await db.get(Organization, owner_id): raise HTTPException(404, "org not found")
        kwargs["organization_id"] = owner_id
    elif owner_type == "loc":
        if not await db.get(Location, owner_id): raise HTTPException(404, "loc not found")
        kwargs["location_id"] = owner_id
    elif owner_type == "svc":
        if not await db.get(Service, owner_id): raise HTTPException(404, "svc not found")
        kwargs["service_id"] = owner_id
    else:
        raise HTTPException(400, "invalid owner_type")

    p = Phone(**payload.model_dump(), **kwargs)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return PhoneOut.from_orm(p)


@router.put("/phones/{phone_id}", response_model=PhoneOut, dependencies=[Depends(require_admin)])
async def update_phone(phone_id: UUID, payload: PhoneIn, db: AsyncSession = Depends(get_db)) -> PhoneOut:
    p = await db.get(Phone, phone_id)
    if not p:
        raise HTTPException(404, "phone not found")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return PhoneOut.from_orm(p)


@router.delete("/phones/{phone_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_phone(phone_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    p = await db.get(Phone, phone_id)
    if not p:
        raise HTTPException(404, "phone not found")
    await db.delete(p)
    await db.commit()


# ── database backup & restore ────────────────────────────

@router.get("/database/export", dependencies=[Depends(require_admin)])
async def admin_export_database(db: AsyncSession = Depends(get_db)) -> Response:
    payload = await export_directory(db)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"navigator-backup-{stamp}.json"
    return Response(
        content=body, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Length": str(len(body))},
    )

@router.post("/database/import", dependencies=[Depends(require_admin)])
async def admin_import_database(
    file: UploadFile = File(...), mode: str = Form("replace"), db: AsyncSession = Depends(get_db),
) -> dict:
    if mode != "replace":
        raise HTTPException(400, f"unsupported import mode: {mode!r}")
    raw = await file.read()
    if len(raw) > 100 * 1024 * 1024:
        raise HTTPException(413, "import exceeds 100MB limit")
    try:
        payload = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, f"invalid JSON: {e}")
    await db.execute(text("SELECT pg_advisory_xact_lock(920112)"))
    try:
        counts = await import_directory(db, payload, mode=mode)
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(400, str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"import failed: {e}")
    return {"ok": True, "mode": mode, "counts": counts}

# ── UI strings & translations ───────────────────────────

class UiStringRow(BaseModel):
    key: str
    english: str
    context: str | None
    translated: str | None          # NULL = not translated for this locale
    translator_signature: str | None
    translated_at: datetime | None


@router.get("/ui-strings", dependencies=[Depends(require_admin)])
async def list_ui_strings(
    locale: str = Query(..., min_length=2, max_length=10),
    db: AsyncSession = Depends(get_db),
) -> list[UiStringRow]:
    stmt = (
        select(UiString, UiStringTranslation)
        .outerjoin(
            UiStringTranslation,
            and_(
                UiStringTranslation.key == UiString.key,
                UiStringTranslation.locale == locale,
            ),
        )
        .order_by(UiString.key)
    )
    rows = (await db.execute(stmt)).all()
    return [
        UiStringRow(
            key=s.key, english=s.english, context=s.context,
            translated=t.translated if t else None,
            translator_signature=t.translator_signature if t else None,
            translated_at=t.translated_at if t else None,
        )
        for s, t in rows
    ]


@router.put(
    "/ui-strings/{key}/translations/{locale}",
    dependencies=[Depends(require_admin)],
)
async def set_translation(
    key: str, locale: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    translated = str(payload.get("translated", "")).strip()
    if not translated:
        raise HTTPException(400, "translated must be non-empty")
    if await db.get(UiString, key) is None:
        raise HTTPException(404, f"unknown key: {key}")

    stmt = pg_insert(UiStringTranslation).values(
        key=key, locale=locale, translated=translated,
        translator_signature="manual",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key", "locale"],
        set_={"translated": translated,
              "translator_signature": "manual",
              "translated_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}


@router.delete(
    "/ui-strings/{key}/translations/{locale}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_translation(
    key: str, locale: str, db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        sa_delete(UiStringTranslation).where(
            UiStringTranslation.key == key,
            UiStringTranslation.locale == locale,
        )
    )
    await db.commit()


class CoverageRow(BaseModel):
    locale: str
    translated: int
    total: int


@router.get("/languages/coverage", dependencies=[Depends(require_admin)])
async def coverage(db: AsyncSession = Depends(get_db)) -> list[CoverageRow]:
    total = (await db.execute(
        select(func.count()).select_from(UiString)
    )).scalar() or 0

    rows = (await db.execute(
        select(UiStringTranslation.locale, func.count())
        .group_by(UiStringTranslation.locale)
    )).all()
    counts = {loc: n for loc, n in rows}

    from ..translator import CHINESE_NAMES
    return sorted(
        [
            CoverageRow(
                locale=loc,
                translated=counts.get(loc, 0),
                total=total,
            )
            for loc in CHINESE_NAMES
            if loc != "en"      # English is the source; it has no row
        ],
        key=lambda r: r.locale,
    )


# ── Translation jobs ─────────────────────────────────────

class StartJobIn(BaseModel):
    mode: str = Field(pattern="^(missing|refresh)$")
    locale: str | None = None      # NULL = all locales


class JobOut(BaseModel):
    id: str
    mode: str
    locale: str | None
    status: str
    total: int
    done: int
    failed: int
    cancel_requested: bool
    error_summary: str | None
    created_at: datetime


def _job_out(j: TranslationJob) -> JobOut:
    return JobOut(
        id=str(j.id), mode=j.mode, locale=j.locale, status=j.status,
        total=j.total, done=j.done, failed=j.failed,
        cancel_requested=j.cancel_requested,
        error_summary=j.error_summary, created_at=j.created_at,
    )


@router.post("/translations/run", dependencies=[Depends(require_admin)])
async def start_translation_job(
    payload: StartJobIn, db: AsyncSession = Depends(get_db),
) -> JobOut:
    from ..translator import run_translation_job

    active = (await db.execute(
        select(func.count()).select_from(TranslationJob).where(
            TranslationJob.status.in_(["pending", "running"])
        )
    )).scalar() or 0
    if active:
        raise HTTPException(409, "a translation job is already running")

    if payload.mode == "refresh":
        if not payload.locale:
            raise HTTPException(400, "refresh requires a locale")
        # Delete first so the "missing" collector sees the work.
        await db.execute(
            sa_delete(UiStringTranslation).where(
                UiStringTranslation.locale == payload.locale
            )
        )

    job = TranslationJob(mode=payload.mode, locale=payload.locale)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Convenience: start on this replica. If this process dies, the
    # startup sweep in main.py will resume it on the next boot.
    import asyncio
    asyncio.create_task(run_translation_job(job.id))

    return _job_out(job)


@router.get("/translations/active", dependencies=[Depends(require_admin)])
async def active_jobs(db: AsyncSession = Depends(get_db)) -> list[JobOut]:
    rows = (await db.execute(
        select(TranslationJob)
        .where(TranslationJob.status.in_(["pending", "running"]))
        .order_by(TranslationJob.created_at.desc())
    )).scalars().all()
    return [_job_out(j) for j in rows]


@router.post(
    "/translations/{job_id}/cancel",
    dependencies=[Depends(require_admin)],
)
async def cancel_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(
        update(TranslationJob)
        .where(
            TranslationJob.id == job_id,
            TranslationJob.status.in_(["pending", "running"]),
        )
        .values(cancel_requested=True)
    )
    await db.commit()
    return {"ok": True}# ── UI strings & translations ───────────────────────────

class UiStringRow(BaseModel):
    key: str
    english: str
    context: str | None
    translated: str | None          # NULL = not translated for this locale
    translator_signature: str | None
    translated_at: datetime | None


@router.get("/ui-strings", dependencies=[Depends(require_admin)])
async def list_ui_strings(
    locale: str = Query(..., min_length=2, max_length=10),
    db: AsyncSession = Depends(get_db),
) -> list[UiStringRow]:
    stmt = (
        select(UiString, UiStringTranslation)
        .outerjoin(
            UiStringTranslation,
            and_(
                UiStringTranslation.key == UiString.key,
                UiStringTranslation.locale == locale,
            ),
        )
        .order_by(UiString.key)
    )
    rows = (await db.execute(stmt)).all()
    return [
        UiStringRow(
            key=s.key, english=s.english, context=s.context,
            translated=t.translated if t else None,
            translator_signature=t.translator_signature if t else None,
            translated_at=t.translated_at if t else None,
        )
        for s, t in rows
    ]


@router.put(
    "/ui-strings/{key}/translations/{locale}",
    dependencies=[Depends(require_admin)],
)
async def set_translation(
    key: str, locale: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    translated = str(payload.get("translated", "")).strip()
    if not translated:
        raise HTTPException(400, "translated must be non-empty")
    if await db.get(UiString, key) is None:
        raise HTTPException(404, f"unknown key: {key}")

    stmt = pg_insert(UiStringTranslation).values(
        key=key, locale=locale, translated=translated,
        translator_signature="manual",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key", "locale"],
        set_={"translated": translated,
              "translator_signature": "manual",
              "translated_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}


@router.delete(
    "/ui-strings/{key}/translations/{locale}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_translation(
    key: str, locale: str, db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        sa_delete(UiStringTranslation).where(
            UiStringTranslation.key == key,
            UiStringTranslation.locale == locale,
        )
    )
    await db.commit()


class CoverageRow(BaseModel):
    locale: str
    translated: int
    total: int


@router.get("/languages/coverage", dependencies=[Depends(require_admin)])
async def coverage(db: AsyncSession = Depends(get_db)) -> list[CoverageRow]:
    total = (await db.execute(
        select(func.count()).select_from(UiString)
    )).scalar() or 0

    rows = (await db.execute(
        select(UiStringTranslation.locale, func.count())
        .group_by(UiStringTranslation.locale)
    )).all()
    counts = {loc: n for loc, n in rows}

    from ..translator import LANGUAGE_NAMES
    return sorted(
        [CoverageRow(locale=loc, translated=counts.get(loc, 0), total=total)
         for loc in LANGUAGE_NAMES],
        key=lambda r: r.locale,
    )


# ── Translation jobs ─────────────────────────────────────

class StartJobIn(BaseModel):
    mode: str = Field(pattern="^(missing|refresh)$")
    locale: str | None = None      # NULL = all locales


class JobOut(BaseModel):
    id: str
    mode: str
    locale: str | None
    status: str
    total: int
    done: int
    failed: int
    cancel_requested: bool
    error_summary: str | None
    created_at: datetime


def _job_out(j: TranslationJob) -> JobOut:
    return JobOut(
        id=str(j.id), mode=j.mode, locale=j.locale, status=j.status,
        total=j.total, done=j.done, failed=j.failed,
        cancel_requested=j.cancel_requested,
        error_summary=j.error_summary, created_at=j.created_at,
    )


@router.post("/translations/run", dependencies=[Depends(require_admin)])
async def start_translation_job(
    payload: StartJobIn, db: AsyncSession = Depends(get_db),
) -> JobOut:
    from ..translator import run_translation_job

    active = (await db.execute(
        select(func.count()).select_from(TranslationJob).where(
            TranslationJob.status.in_(["pending", "running"])
        )
    )).scalar() or 0
    if active:
        raise HTTPException(409, "a translation job is already running")

    if payload.mode == "refresh":
        if not payload.locale:
            raise HTTPException(400, "refresh requires a locale")
        # Delete first so the "missing" collector sees the work.
        await db.execute(
            sa_delete(UiStringTranslation).where(
                UiStringTranslation.locale == payload.locale
            )
        )

    job = TranslationJob(mode=payload.mode, locale=payload.locale)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Convenience: start on this replica. If this process dies, the
    # startup sweep in main.py will resume it on the next boot.
    import asyncio
    asyncio.create_task(run_translation_job(job.id))

    return _job_out(job)


@router.get("/translations/active", dependencies=[Depends(require_admin)])
async def active_jobs(db: AsyncSession = Depends(get_db)) -> list[JobOut]:
    rows = (await db.execute(
        select(TranslationJob)
        .where(TranslationJob.status.in_(["pending", "running"]))
        .order_by(TranslationJob.created_at.desc())
    )).scalars().all()
    return [_job_out(j) for j in rows]


@router.post(
    "/translations/{job_id}/cancel",
    dependencies=[Depends(require_admin)],
)
async def cancel_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(
        update(TranslationJob)
        .where(
            TranslationJob.id == job_id,
            TranslationJob.status.in_(["pending", "running"]),
        )
        .values(cancel_requested=True)
    )
    await db.commit()
    return {"ok": True}