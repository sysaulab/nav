from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai.base import ModelSpec
from ..ai.registry import get_registry, reload_registry
from ..config import Settings
from ..db import get_db
from ..models import (
    AppSetting, Location, Organization, Service, ServiceAtLocation,
)
from ..schemas import (
    LocationIn, LocationOut, LocationServiceIn, OrganizationIn, OrganizationOut,
    ServiceIn, ServiceOut,
)
from ..settings_store import delete_app_setting, set_app_setting

from fastapi import File, Form, UploadFile
from fastapi.responses import Response
from ..backup import export_directory, import_directory
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
    cfg = _cfg()
    if not cfg.admin_token:
        raise HTTPException(503, "admin is not configured on this server")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != cfg.admin_token:
        raise HTTPException(401, "invalid admin token")


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
    }


class DefaultsIn(BaseModel):
    chat: str | None = None
    finalize: str | None = None


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

    reg = await reload_registry(db, _cfg())
    return {
        "chat": reg.default_chat_id(),
        "finalize": reg.default_finalize_id(),
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


# ── directory: organizations ─────────────────────────────

class OrganizationsPage(BaseModel):
    items: list[OrganizationOut]
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

    return OrganizationsPage(
        items=[OrganizationOut.model_validate(r) for r in rows],
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

    # Strict cascade: Org -> Location -> Service
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

class LocationWithCount(BaseModel):
    id: str
    name: str | None
    address: str | None
    latitude: str | None
    longitude: str | None
    service_count: int


@router.get("/organizations/{org_id}/locations", response_model=list[LocationWithCount], dependencies=[Depends(require_admin)])
async def list_org_locations(org_id: UUID, db: AsyncSession = Depends(get_db)) -> list[LocationWithCount]:
    if not await db.get(Organization, org_id):
        raise HTTPException(404, "organization not found")

    stmt = (
        select(
            Location.id, Location.name, Location.address,
            Location.latitude, Location.longitude,
            func.count(ServiceAtLocation.id).label("svc_count"),
        )
        .outerjoin(ServiceAtLocation, ServiceAtLocation.location_id == Location.id)
        .where(Location.organization_id == org_id)
        .group_by(Location.id)
        .order_by(Location.name.nulls_last(), Location.id)
    )
    rows = (await db.execute(stmt)).all()
    return [
        LocationWithCount(
            id=str(r.id), name=r.name, address=r.address,
            latitude=str(r.latitude) if r.latitude is not None else None,
            longitude=str(r.longitude) if r.longitude is not None else None,
            service_count=int(r.svc_count),
        )
        for r in rows
    ]


@router.post("/organizations/{org_id}/locations", response_model=LocationOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_location(org_id: UUID, payload: LocationIn, db: AsyncSession = Depends(get_db)) -> LocationOut:
    if not await db.get(Organization, org_id):
        raise HTTPException(404, "organization not found")
    
    # Fix: exclude organization_id to prevent duplicate kwargs
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
    for k, v in payload.model_dump().items():
        if k != "organization_id": # Prevent moving orgs via this endpoint
            setattr(loc, k, v)
    await db.commit()
    await db.refresh(loc)
    return LocationOut.model_validate(loc)


@router.delete("/locations/{loc_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_location(loc_id: UUID, db: AsyncSession = Depends(get_db)) -> None:
    loc = await db.get(Location, loc_id)
    if not loc:
        raise HTTPException(404, "location not found")

    svc_ids = (await db.execute(select(Service.id).where(Service.organization_id == loc.organization_id))).scalars().all()
    # Filter svc_ids to only those actually at this location
    sal_svc_ids = (await db.execute(select(ServiceAtLocation.service_id).where(ServiceAtLocation.location_id == loc_id))).scalars().all()
    
    if sal_svc_ids:
        await db.execute(sa_delete(ServiceAtLocation).where(ServiceAtLocation.service_id.in_(sal_svc_ids)))
        await db.execute(sa_delete(Service).where(Service.id.in_(sal_svc_ids)))

    await db.delete(loc)
    await db.commit()


# ── directory: services ──────────────────────────────────

@router.get("/locations/{loc_id}/services", response_model=list[ServiceOut], dependencies=[Depends(require_admin)])
async def list_loc_services(loc_id: UUID, db: AsyncSession = Depends(get_db)) -> list[ServiceOut]:
    if not await db.get(Location, loc_id):
        raise HTTPException(404, "location not found")

    stmt = (
        select(Service)
        .join(ServiceAtLocation, ServiceAtLocation.service_id == Service.id)
        .where(ServiceAtLocation.location_id == loc_id)
        .order_by(Service.name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [ServiceOut.model_validate(r) for r in rows]


@router.post("/locations/{loc_id}/services", response_model=ServiceOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_service(loc_id: UUID, payload: LocationServiceIn, db: AsyncSession = Depends(get_db)) -> ServiceOut:
    loc = await db.get(Location, loc_id)
    if not loc or not loc.organization_id:
        raise HTTPException(400, "location not found or has no organization")

    # Fix: exclude organization_id, use LocationServiceIn which allows it to be optional
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
    
    # Fix: exclude organization_id from update
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

# ── database backup & restore ────────────────────────────

@router.get("/database/export", dependencies=[Depends(require_admin)])
async def admin_export_database(db: AsyncSession = Depends(get_db)) -> Response:
    """Download a JSON snapshot of the directory tables."""
    payload = await export_directory(db)
    body = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"navigator-backup-{stamp}.json"

    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(body)),
        },
    )

@router.post("/database/import", dependencies=[Depends(require_admin)])
async def admin_import_database(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Replace the directory from a JSON snapshot.

    Wrapped in a single transaction and serialised by a Postgres
    advisory lock. A failure leaves the directory unchanged.
    """
    if mode != "replace":
        raise HTTPException(400, f"unsupported import mode: {mode!r}")

    raw = await file.read()
    if len(raw) > 100 * 1024 * 1024:  # 100MB cap
        raise HTTPException(413, "import exceeds 100MB limit")

    try:
        payload = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, f"invalid JSON: {e}")

    # Serialise concurrent imports across replicas.
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