from __future__ import annotations

import json
import math
import re
from ..geocode import photon_display_name
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status

SESSION_COOKIE = "nav_session"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

MAX_TOOL_ROUNDS = 5

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_service_details",
        "description": (
            "Expand one service from the nearby-services list by its "
            "bracketed index (e.g. 17 or [17]). Returns full detail: "
            "description, eligibility, how to apply, fees, contact. The "
            "prompt lists each service by name only — call this for any "
            "service you plan to recommend or discuss in depth."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "index": {
                    "type": "string",
                    "description": "The bracketed index from the list, e.g. '17' or '[17]'.",
                }
            },
            "required": ["index"],
        },
    },
}


def _read_session_cookie(request: Request) -> UUID | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _set_session_cookie(response: Response, sid: UUID) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        str(sid),
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )

from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_db
from ..models import (
    InterviewSession, Location, Service, ServiceAtLocation, SessionDocument,
)
from ..prompt import assemble_prompt, render_document
from ..runtime import get_runtime
from ..sanitize import filter_sanitizer_output
from ..schemas import (
    ChatRequestIn,
    ContextPromptOut,
    DocumentMetaOut,
    InterviewSessionOut,
    PostalCodeIn,
    SessionLocationOut,
    SkippedDocumentOut,
)
from ..tokens import estimate_tokens, estimate_chat_tokens
from ..ai.base import ChatEvent, ModelSpec
from ..ai.registry import client_for, get_registry

router = APIRouter(prefix="/interviews", tags=["interviews"])

_settings: Settings | None = None


def bind_settings(settings: Settings) -> None:
    global _settings
    _settings = settings


def _cfg() -> Settings:
    assert _settings is not None, "bind_settings() not called"
    return _settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── session helpers ───────────────────────────────────────

async def _require_active(
    sid: UUID, request: Request, db: AsyncSession
) -> InterviewSession:
    sess = await db.get(InterviewSession, sid)
    if sess is None:
        raise HTTPException(404, "session not found")
    if _read_session_cookie(request) != sid:
        raise HTTPException(404, "session not found")
    if sess.status == "ended":
        raise HTTPException(409, "session has ended")
    now = _now()
    if sess.expires_at <= now:
        sess.status = "expired"
        await db.commit()
        raise HTTPException(410, "session expired")
    sess.expires_at = now + timedelta(minutes=_cfg().session_idle_minutes)
    await db.commit()
    return sess


async def _require_located(sess: InterviewSession) -> None:
    if sess.postal_code is None or sess.origin_lat is None or sess.origin_lng is None:
        raise HTTPException(400, "set a postal code before continuing")


# ── sessions ─────────────────────────────────────────────

@router.post("", response_model=InterviewSessionOut)
async def create_or_resume_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    cfg = _cfg()
    now = _now()
    sid = _read_session_cookie(request)

    if sid is not None:
        sess = await db.get(InterviewSession, sid)
        if sess is not None and sess.status == "active" and sess.expires_at > now:
            sess.expires_at = now + timedelta(minutes=cfg.session_idle_minutes)
            await db.commit()
            await db.refresh(sess)
            return sess
        if sess is not None:
            await db.execute(sa_delete(InterviewSession).where(InterviewSession.id == sess.id))
            await db.commit()

    sess = InterviewSession(
        status="active",
        expires_at=now + timedelta(minutes=cfg.session_idle_minutes),
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    _set_session_cookie(response, sess.id)
    return sess


@router.get("/active", response_model=InterviewSessionOut | None)
async def get_active_session(
    request: Request, db: AsyncSession = Depends(get_db)
):
    sid = _read_session_cookie(request)
    if sid is None:
        return None
    sess = await db.get(InterviewSession, sid)
    if sess is None or sess.status != "active":
        return None
    if sess.expires_at <= _now():
        return None
    return sess


@router.delete("/{sid}", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(
    sid: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    if _read_session_cookie(request) != sid:
        raise HTTPException(404, "session not found")
    sess = await db.get(InterviewSession, sid)
    if sess is None:
        raise HTTPException(404, "session not found")
    await db.execute(sa_delete(InterviewSession).where(InterviewSession.id == sid))
    await db.commit()


# ── location ─────────────────────────────────────────────

@router.get("/{sid}/location", response_model=SessionLocationOut)
async def get_location(
    sid: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    sess = await _require_active(sid, request, db)
    return SessionLocationOut(
        postal_code=sess.postal_code,
        origin_lat=sess.origin_lat,
        origin_lng=sess.origin_lng,
        origin_display_name=sess.origin_display_name,
    )


@router.post("/{sid}/location", response_model=SessionLocationOut)
async def set_location(
    sid: UUID,
    payload: PostalCodeIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    sess = await _require_active(sid, request, db)
    cfg = _cfg()

    if payload.lat is not None and payload.lng is not None:
        lat = payload.lat
        lng = payload.lng
        display_name = payload.display_name or payload.postal_code
    else:
        endpoint = cfg.photon_endpoint.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{endpoint}/api",
                    params={"q": payload.postal_code, "limit": 1, "lang": "en"},
                )
        except httpx.RequestError as e:
            raise HTTPException(502, f"photon unreachable: {e}")
        if r.status_code >= 400:
            raise HTTPException(502, f"photon returned {r.status_code}")

        try:
            data = r.json()
        except ValueError as e:
            raise HTTPException(502, f"photon returned non-JSON: {e}")

        features = data.get("features") or []
        if not features:
            raise HTTPException(404, f"no match for {payload.postal_code!r}")

        feat = features[0]
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            raise HTTPException(502, "photon returned malformed geometry")
        try:
            lon_f, lat_f = float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            raise HTTPException(502, "photon returned malformed coordinates")

        display_name = photon_display_name(props) or payload.postal_code
        lat = Decimal(str(lat_f))
        lng = Decimal(str(lon_f))

    sess.postal_code = payload.postal_code.strip()
    sess.origin_lat = lat
    sess.origin_lng = lng
    sess.origin_display_name = display_name[:512]

    n = get_runtime().current().nearby
    rows = await _nearby_services(
        db, lat, lng, n.radius_km, n.location_limit, n.index_limit,
    )
    sess.nearby_service_ids = [str(svc.id) for svc, _l, _d in rows]
    sess.revealed_service_indices = []

    await db.commit()
    await db.refresh(sess)

    return SessionLocationOut(
        postal_code=sess.postal_code,
        origin_lat=sess.origin_lat,
        origin_lng=sess.origin_lng,
        origin_display_name=sess.origin_display_name,
    )


# ── documents ────────────────────────────────────────────

@router.get("/{sid}/documents", response_model=list[DocumentMetaOut])
async def list_documents(
    sid: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    await _require_active(sid, request, db)
    rows = (await db.execute(
        select(SessionDocument)
        .where(SessionDocument.session_id == sid)
        .order_by(SessionDocument.created_at)
    )).scalars().all()
    return rows


@router.post(
    "/{sid}/documents",
    response_model=DocumentMetaOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    sid: UUID,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    cfg = _cfg()
    await _require_active(sid, request, db)

    existing = (await db.execute(
        select(SessionDocument).where(SessionDocument.session_id == sid)
    )).scalars().all()
    if len(existing) >= cfg.max_documents_per_session:
        raise HTTPException(
            409,
            f"session holds {len(existing)} documents (max {cfg.max_documents_per_session})",
        )

    raw = await file.read()
    if len(raw) > cfg.max_upload_bytes:
        raise HTTPException(413, f"file exceeds {cfg.max_upload_bytes} bytes")

    filename = file.filename or "upload"

    try:
        async with httpx.AsyncClient(timeout=cfg.sanitizer_timeout_s) as client:
            resp = await client.post(
                cfg.sanitizer_endpoint,
                files={
                    "file": (
                        filename,
                        raw,
                        file.content_type or "application/octet-stream",
                    )
                },
            )
    except httpx.RequestError as e:
        raise HTTPException(502, f"sanitizer unreachable: {e}")

    if resp.status_code == 413:
        raise HTTPException(413, "sanitizer rejected: too large")
    if resp.status_code >= 500:
        raise HTTPException(502, f"sanitizer error {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        raise HTTPException(502, f"sanitizer returned {resp.status_code}")
    try:
        sanitizer_doc = resp.json()
    except ValueError as e:
        raise HTTPException(502, f"sanitizer returned non-JSON: {e}")

    filtered = filter_sanitizer_output(sanitizer_doc)
    est = estimate_tokens(filtered, model_name=cfg.tokenizer_model)

    quality = filtered["quality"]
    doc_status = "ready"
    skip_reason: str | None = None

    if quality == "quarantine":
        doc_status = "quarantine"
        reasons = sanitizer_doc.get("quality", {}).get("reasons", [])
        skip_reason = "; ".join(reasons) or "quarantined"
    elif est > cfg.document_budget_tokens:
        doc_status = "skipped_too_large"
        skip_reason = f"estimated {est} tokens > budget {cfg.document_budget_tokens}"

    record = SessionDocument(
        session_id=sid,
        filename=filtered["filename"],
        mime_type=file.content_type,
        size_bytes=len(raw),
        route=sanitizer_doc["source"]["route"],
        quality_status=quality,
        page_count=filtered["page_count"],
        block_count=sum(len(p["blocks"]) for p in filtered["pages"]),
        token_estimate=est,
        payload_json=json.dumps(filtered),
        status=doc_status,
        skip_reason=skip_reason,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.get("/{sid}/documents/{did}")
async def get_document(
    sid: UUID, did: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    await _require_active(sid, request, db)
    doc = await db.get(SessionDocument, did)
    if doc is None or doc.session_id != sid:
        raise HTTPException(404, "document not found")
    return json.loads(doc.payload_json)


@router.delete("/{sid}/documents/{did}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    sid: UUID, did: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    await _require_active(sid, request, db)
    doc = await db.get(SessionDocument, did)
    if doc is None or doc.session_id != sid:
        raise HTTPException(404, "document not found")
    await db.delete(doc)
    await db.commit()


# ── nearby services ──────────────────────────────────────
_EARTH_R_KM = 6371.0088
_DEG_PER_KM = 1.0 / 111.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R_KM * math.asin(math.sqrt(a))


async def _closest_location_per_service(
    db: AsyncSession,
    service_ids: list[UUID],
    origin_lat: float,
    origin_lng: float,
) -> dict[UUID, tuple[Location, float | None]]:
    if not service_ids:
        return {}
    loc_rows = (await db.execute(
        select(ServiceAtLocation.service_id, Location)
        .join(Location, Location.id == ServiceAtLocation.location_id)
        .where(ServiceAtLocation.service_id.in_(service_ids))
    )).all()
    result: dict[UUID, tuple[Location, float | None]] = {}
    for sal_sid, loc in loc_rows:
        if loc.latitude is None or loc.longitude is None:
            # Global — takes precedence over any local location.
            result[sal_sid] = (loc, None)
            continue
        d = _haversine_km(
            origin_lat, origin_lng,
            float(loc.latitude), float(loc.longitude),
        )
        prev = result.get(sal_sid)
        if prev is None:
            result[sal_sid] = (loc, d)
        elif prev[1] is not None and d < prev[1]:
            result[sal_sid] = (loc, d)
    return result


async def _nearby_services(
    db: AsyncSession,
    lat: Decimal,
    lng: Decimal,
    radius_km: float,
    location_limit: int,
    index_limit: int,
) -> list[tuple[Service, Location, float | None]]:
    lat0, lng0 = float(lat), float(lng)

    deg_pad_lat = radius_km * _DEG_PER_KM
    cos_lat = max(math.cos(math.radians(lat0)), 0.01)
    deg_pad_lng = radius_km * _DEG_PER_KM / cos_lat

    # No coordinate predicate in SQL — NULL-coord rows are global services
    # (crisis lines, province-wide info lines) that apply to every
    # customer. They rank first in the result. Coordinates are only used
    # for the *local* bucket; the haversine filter below drops locals
    # outside radius_km.
    stmt = (
        select(Service, Location)
        .join(ServiceAtLocation, ServiceAtLocation.service_id == Service.id)
        .join(Location, Location.id == ServiceAtLocation.location_id)
        .where(Service.status == "active")
    )
    rows = (await db.execute(stmt)).all()

    # Per-service: (Service, Location, distance_or_None).
    # Global (NULL coords) takes precedence over any local.
    by_service: dict[UUID, tuple[Service, Location, float | None]] = {}
    for svc, loc in rows:
        is_global = loc.latitude is None or loc.longitude is None
        if is_global:
            existing = by_service.get(svc.id)
            if existing is None or existing[2] is not None:
                by_service[svc.id] = (svc, loc, None)
            continue

        d = _haversine_km(lat0, lng0, float(loc.latitude), float(loc.longitude))
        if d > radius_km:
            continue
        existing = by_service.get(svc.id)
        if existing is None:
            by_service[svc.id] = (svc, loc, d)
        elif existing[2] is not None and d < existing[2]:
            by_service[svc.id] = (svc, loc, d)

    # Group by location.
    by_location: dict[UUID, tuple[Location, float | None, list[Service]]] = {}
    for svc, loc, d in by_service.values():
        entry = by_location.get(loc.id)
        if entry is None:
            by_location[loc.id] = (loc, d, [svc])
        else:
            entry[2].append(svc)

    global_locs = [v for v in by_location.values() if v[1] is None]
    local_locs = [v for v in by_location.values() if v[1] is not None]

    global_locs.sort(key=lambda t: (t[0].name or "").lower())
    local_locs.sort(key=lambda t: t[1])
    local_locs = local_locs[:location_limit]

    # Globals first — they apply everywhere, so they must appear before
    # any distance-sorted local entry. They do NOT consume location_limit
    # (that cap is "how many physical places to show"); they only count
    # against index_limit, which is the total services budget.
    result: list[tuple[Service, Location, float | None]] = []
    for loc, _d, svcs in global_locs:
        for svc in sorted(svcs, key=lambda s: (s.name or "").lower()):
            result.append((svc, loc, None))
            if len(result) >= index_limit:
                return result
    for loc, d, svcs in local_locs:
        for svc in sorted(svcs, key=lambda s: (s.name or "").lower()):
            result.append((svc, loc, d))
            if len(result) >= index_limit:
                return result
    return result

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "SHELTER":     ("shelter", "housing", "homeless", "residence", "hostel"),
    "FOOD":        ("food", "meal", "pantry", "kitchen", "grocer", "nutrition"),
    "HEALTH":      ("health", "clinic", "medical", "dental", "nurse", "pharmacy"),
    "LEGAL":       ("legal", "law", "attorney", "immigration", "court"),
    "EMPLOYMENT":  ("job", "employ", "career", "work"),
    "EDUCATION":   ("school", "educat", "train", "learn", "literacy"),
    "COUNSEL":     ("counsel", "mental", "crisis", "therapy", "support"),
    "FINANCE":     ("financ", "money", "benefit", "assistance", "income"),
    "CHILD":       ("child", "youth", "family", "parent", "daycare"),
    "TRANSPORT":   ("transport", "transit", "bus", "ride"),
}


def _category_of(svc: Service) -> str:
    text = (svc.name or "").lower()
    for cat, keys in _CATEGORY_KEYWORDS.items():
        if any(k in text for k in keys):
            return cat
    first = (svc.name or "").split()
    return first[0].upper() if first else "OTHER"


def _render_service_full(
    idx: int, svc: Service, loc: Location | None, dist_km: float | None,
) -> str:
    cat = _category_of(svc)
    dist_label = f"{dist_km:.1f} km" if dist_km is not None else "Global"
    lines = [f"\n### [{idx:02d}] {cat} — {dist_label}", f"**{svc.name}**"]

    if loc:
        if loc.latitude is not None and loc.longitude is not None:
            addr = loc.address or f"{loc.latitude}, {loc.longitude}"
            lines.append(f"- Location: {loc.name or '(unnamed)'} — {addr}")
        elif loc.name or loc.address:
            parts = [p for p in (loc.name, loc.address) if p]
            lines.append(f"- Location: {' — '.join(parts)}")

    if svc.description:
        lines.append(f"- {svc.description[:500]}")
    if svc.eligibility_description:
        lines.append(f"- Eligibility: {svc.eligibility_description[:300]}")
    if svc.application_process:
        lines.append(f"- How to apply: {svc.application_process[:300]}")
    if svc.fees_description:
        lines.append(f"- Fees: {svc.fees_description[:200]}")
    if svc.email:
        lines.append(f"- Email: {svc.email}")
    if svc.url:
        lines.append(f"- URL: {svc.url}")
    return "\n".join(lines)


def _render_nearby(
    items: list[tuple[int, Service | None, Location | None, float | None]],
    postal_code: str,
    display_name: str | None,
    revealed: set[int],
) -> str:
    loc = postal_code or "unknown"
    if display_name and display_name != loc:
        loc = f"{loc} — {display_name}"
    header = f"## Customer location\n{loc}"
    if not items:
        return header + "\n\nNo services were found near this location."

    # Split by distance presence. Globals (dist None, svc present) come
    # first, because they apply everywhere. Orphans (svc None) land in
    # the local bucket when their sentinel is 0.0, or in globals when
    # their sentinel is None; either way they render as
    # "(no longer available)" and are not treated as a real entry.
    globals_items: list = []
    locals_items: list = []
    for it in items:
        if it[3] is None:
            globals_items.append(it)
        else:
            locals_items.append(it)

    lines = [header]

    if globals_items:
        lines.append("")
        lines.append("## Global services (apply everywhere)")
        current_loc_id: UUID | None = None
        for idx, svc, loc_obj, _d in globals_items:
            if svc is None or loc_obj is None:
                lines.append(f"[{idx:02d}] (no longer available)")
                continue
            if loc_obj.id != current_loc_id:
                if current_loc_id is not None:
                    lines.append("")
                lines.append(loc_obj.name or "(unnamed location)")
                if loc_obj.address:
                    lines.append(loc_obj.address)
                current_loc_id = loc_obj.id
            lines.append(f"[{idx:02d}] {svc.name}")

    if locals_items:
        lines.append("")
        lines.append("## Nearby services")
        current_loc_id = None
        for idx, svc, loc_obj, dist in locals_items:
            if svc is None or loc_obj is None:
                lines.append(f"[{idx:02d}] (no longer available)")
                continue
            if loc_obj.id != current_loc_id:
                if current_loc_id is not None:
                    lines.append("")
                name = loc_obj.name or "(unnamed location)"
                lines.append(f"{name} ({dist:.1f}km away)")
                if loc_obj.address:
                    lines.append(loc_obj.address)
                current_loc_id = loc_obj.id
            lines.append(f"[{idx:02d}] {svc.name}")

    lines.append(
        "\nCall `get_service_details(n)` to expand any service. "
        "Each entry above lists only the service name and its location — "
        "the tool returns description, eligibility, application process, "
        "fees, and contact."
    )

    if revealed:
        lines.append("\n## Additional details requested by the customer")
        for i in sorted(revealed):
            if i < 0 or i >= len(items):
                continue
            idx, svc, loc_obj, d = items[i]
            if svc is None:
                lines.append(f"\n### [{idx:02d}] (no longer available)")
            else:
                lines.append(_render_service_full(idx, svc, loc_obj, d))

    return "\n".join(lines)


def _parse_index(raw) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    while s and s[0] in "[(":
        s = s[1:]
    while s and s[-1] in "])":
        s = s[:-1]
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


async def _lookup_location_and_distance(
    db: AsyncSession, svc: Service, sess: InterviewSession,
) -> tuple[Location | None, float | None]:
    origin_lat = float(sess.origin_lat) if sess.origin_lat is not None else 0.0
    origin_lng = float(sess.origin_lng) if sess.origin_lng is not None else 0.0
    hits = await _closest_location_per_service(db, [svc.id], origin_lat, origin_lng)
    return hits.get(svc.id, (None, None))


async def _fetch_nearby_by_ids(
    db: AsyncSession, ids: list[str], sess: InterviewSession,
) -> list[tuple[int, Service | None, Location | None, float]]:
    if not ids:
        return []

    uuids: list[UUID | None] = []
    for raw in ids:
        try:
            uuids.append(UUID(raw))
        except (ValueError, TypeError):
            uuids.append(None)
    valid = [u for u in uuids if u is not None]

    services: dict[UUID, Service] = {}
    if valid:
        svc_rows = (
            await db.execute(select(Service).where(Service.id.in_(valid)))
        ).scalars().all()
        services = {s.id: s for s in svc_rows}

    origin_lat = float(sess.origin_lat) if sess.origin_lat is not None else 0.0
    origin_lng = float(sess.origin_lng) if sess.origin_lng is not None else 0.0
    locs_by_svc = await _closest_location_per_service(
        db, list(services.keys()), origin_lat, origin_lng,
    )

    out: list[tuple[int, Service | None, Location | None, float | None]] = []
    for idx, u in enumerate(uuids):
        if u is None or u not in services:
            out.append((idx, None, None, None))
            continue
        svc = services[u]
        loc, dist = locs_by_svc.get(u, (None, None))
        out.append((idx, svc, loc, dist))
    return out


def _card_payload(
    idx: int, svc: Service, loc: Location | None, dist_km: float | None,
) -> dict:
    return {
        "index": idx,
        "service": {
            "id": str(svc.id),
            "name": svc.name,
            "category": _category_of(svc),
            "status": svc.status,
            "distance_km": round(dist_km, 2) if dist_km is not None else None,
            "location_name": loc.name if loc else None,
            "address": loc.address if loc else None,
            "description": svc.description,
            "eligibility_description": svc.eligibility_description,
            "application_process": svc.application_process,
            "fees_description": svc.fees_description,
            "email": svc.email,
            "url": svc.url,
        },
    }


async def _execute_get_service_details(
    index_arg, sess: InterviewSession, db: AsyncSession,
) -> tuple[str, dict | None]:
    idx = _parse_index(index_arg)
    if idx is None:
        return "error: index must be an integer like 17 or [17]", None

    ids = sess.nearby_service_ids or []
    if not ids:
        return "error: no nearby services available for this session", None
    if idx < 0 or idx >= len(ids):
        return (
            f"error: index {idx} out of range; the list has {len(ids)} entries",
            None,
        )
    try:
        svc_uuid = UUID(ids[idx])
    except ValueError:
        return f"error: malformed id at index {idx}", None

    svc = await db.get(Service, svc_uuid)
    if svc is None:
        return f"error: service at index {idx} no longer exists", None

    loc, dist = await _lookup_location_and_distance(db, svc, sess)
    text = _render_service_full(idx, svc, loc, dist)
    card = _card_payload(idx, svc, loc, dist)

    revealed = set(sess.revealed_service_indices or [])
    if idx not in revealed:
        revealed.add(idx)
        sess.revealed_service_indices = sorted(revealed)
        await db.commit()

    return text, card


# ── context assembly ─────────────────────────────────────

def _render_session_context(sess: InterviewSession) -> str:
    started = sess.created_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    local = started.astimezone()

    day = local.day
    suffix = (
        "th" if 11 <= day <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    )
    date_str = f"{local.strftime('%A, %B')} {day}{suffix}, {local.year}"

    hour = local.hour
    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 17:
        period = "afternoon"
    elif 17 <= hour < 21:
        period = "evening"
    else:
        period = "night"

    tz_label = local.strftime("%Z") or "UTC"
    time_str = local.strftime("%H:%M")

    return (
        f"## Session context\n"
        f"Today is {date_str}. The conversation started at "
        f"{time_str} {tz_label} ({period}). Some time may have passed "
        f"since then."
    )


async def _build_chat_context(
    sid: UUID, db: AsyncSession, base: str | None = None
):
    if base is None:
        base = get_runtime().current().chat_prompt
    cfg = _cfg()
    sess = await db.get(InterviewSession, sid)
    docs = (await db.execute(
        select(SessionDocument)
        .where(SessionDocument.session_id == sid)
        .order_by(SessionDocument.created_at)
    )).scalars().all()

    included: list[SessionDocument] = []
    skipped: list[dict] = []
    used = 0

    for doc in docs:
        if doc.status != "ready":
            skipped.append({
                "id": doc.id,
                "filename": doc.filename,
                "reason": doc.skip_reason or doc.status,
                "token_estimate": doc.token_estimate,
            })
            continue
        if used + doc.token_estimate <= cfg.document_budget_tokens:
            included.append(doc)
            used += doc.token_estimate
        else:
            skipped.append({
                "id": doc.id,
                "filename": doc.filename,
                "reason": "budget_exceeded",
                "token_estimate": doc.token_estimate,
                "remaining_budget": cfg.document_budget_tokens - used,
            })

    rendered = [render_document(json.loads(d.payload_json)) for d in included]

    if sess is not None:
        enriched_base = base + "\n\n" + _render_session_context(sess)
    else:
        enriched_base = base

    system_prompt = assemble_prompt(enriched_base, rendered)

    if sess and sess.origin_lat is not None and sess.origin_lng is not None:
        items = await _fetch_nearby_by_ids(db, sess.nearby_service_ids or [], sess)
        if not items:
            n = get_runtime().current().nearby
            rows = await _nearby_services(
                db, sess.origin_lat, sess.origin_lng,
                n.radius_km, n.location_limit, n.index_limit,
            )
            sess.nearby_service_ids = [str(svc.id) for svc, _l, _d in rows]
            await db.commit()
            items = [
                (i, svc, loc, d) for i, (svc, loc, d) in enumerate(rows)
            ]
        block = _render_nearby(
            items,
            sess.postal_code or "unknown",
            sess.origin_display_name,
            set(sess.revealed_service_indices or []),
        )
        system_prompt += "\n\n" + block
        used += estimate_tokens(block, model_name=cfg.tokenizer_model)

    return system_prompt, included, skipped, used


@router.post("/{sid}/context-prompt", response_model=ContextPromptOut)
async def get_context_prompt(
    sid: UUID,
    payload: ChatRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_active(sid, request, db)
    cfg = _cfg()
    spec = get_registry().default_chat()
    
    system_prompt, included, skipped, _ = await _build_chat_context(sid, db)
    
    prompt_tokens = estimate_tokens(system_prompt, model_name=cfg.tokenizer_model)
    
    msgs = [{"role": m.role, "content": m.content} for m in payload.messages if m.role in ("user", "assistant")]
    chat_tokens = estimate_chat_tokens(msgs, model_name=cfg.tokenizer_model)
    
    return ContextPromptOut(
        system_prompt=system_prompt,
        included=[DocumentMetaOut.model_validate(d) for d in included],
        skipped=[SkippedDocumentOut(**s) for s in skipped],
        total_tokens=prompt_tokens + chat_tokens,
        budget_tokens=spec.budget_tokens,
        context_window=spec.context_window,
        output_reserve_tokens=spec.max_output_tokens,
    )


# ── chat proxy ───────────────────────────────────────────

def _wire_delta(text: str) -> bytes:
    return (json.dumps({"message": {"content": text}}) + "\n").encode()


def _wire_card(card: dict) -> bytes:
    return (json.dumps({
        "event": "service_card",
        "index": card["index"],
        "service": card["service"],
    }) + "\n").encode()


def _wire_error(message: str) -> bytes:
    return (json.dumps({"error": message}) + "\n").encode()


def _stream_with_tools(
    spec: ModelSpec,
    messages: list[dict],
    tools: list[dict],
    *,
    db: AsyncSession,
    sess: InterviewSession,
) -> StreamingResponse:
    async def stream():
        client = client_for(spec)
        for _round in range(MAX_TOOL_ROUNDS):
            tool_events: list[ChatEvent] = []
            assistant_text = ""
            errored = False

            async for ev in client.stream_chat(spec, messages, tools=tools):
                if ev.kind == "delta" and ev.text:
                    assistant_text += ev.text
                    yield _wire_delta(ev.text)
                elif ev.kind == "tool":
                    tool_events.append(ev)
                elif ev.kind == "done":
                    break
                elif ev.kind == "error":
                    yield _wire_error(ev.error or "unknown model error")
                    errored = True
                    break

            if errored:
                return
            if not tool_events:
                return

            messages.append({
                "role": "assistant",
                "content": assistant_text,
                "tool_calls": [
                    {
                        "function": {
                            "name": t.tool_name,
                            "arguments": t.tool_arguments or {},
                        },
                    }
                    for t in tool_events
                ],
            })

            emitted_cards: set[int] = set()
            for t in tool_events:
                if t.tool_name == "get_service_details":
                    text, card = await _execute_get_service_details(
                        (t.tool_arguments or {}).get("index"), sess, db,
                    )
                    if card is not None and card["index"] not in emitted_cards:
                        emitted_cards.add(card["index"])
                        yield _wire_card(card)
                    messages.append({"role": "tool", "content": text})
                else:
                    messages.append({
                        "role": "tool",
                        "content": f"unknown tool: {t.tool_name}",
                    })

        yield _wire_error("tool loop exceeded max rounds")

    return StreamingResponse(stream(), media_type="application/x-ndjson")


def _stream_simple(
    spec: ModelSpec, messages: list[dict],
) -> StreamingResponse:
    async def stream():
        client = client_for(spec)
        async for ev in client.stream_chat(spec, messages):
            if ev.kind == "delta" and ev.text:
                yield _wire_delta(ev.text)
            elif ev.kind == "error":
                yield _wire_error(ev.error or "unknown model error")
                return
            elif ev.kind == "done":
                return

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/{sid}/chat")
async def chat(
    sid: UUID,
    payload: ChatRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    sess = await _require_active(sid, request, db)
    await _require_located(sess)
    spec = get_registry().default_chat()

    system_prompt, _included, _skipped, _used = await _build_chat_context(sid, db)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in payload.messages:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})

    return _stream_with_tools(
        spec, messages, [TOOL_SCHEMA],
        db=db, sess=sess,
    )


# ── final plan ───────────────────────────────────────────


@router.post("/{sid}/finalize")
async def finalize(
    sid: UUID,
    payload: ChatRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    sess = await _require_active(sid, request, db)
    await _require_located(sess)
    spec = get_registry().default_finalize()

    system_prompt, _included, _skipped, _used = await _build_chat_context(
        sid, db, base=get_runtime().current().finalize_prompt
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in payload.messages:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
    messages.append({
        "role": "user",
        "content": "Please produce the final action plan and referrals now.",
    })

    return _stream_simple(spec, messages)