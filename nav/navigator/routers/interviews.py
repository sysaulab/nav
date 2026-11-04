"""Interview session + document upload + chat orchestration.

  POST   /interviews                        → create-or-resume active session
  GET    /interviews/active                 → current active session or null
  DELETE /interviews/{sid}                  → end session (cascade deletes docs)
  POST   /interviews/{sid}/location         → set postal code, geocode, unlock chat
  GET    /interviews/{sid}/location         → current session origin
  POST   /interviews/{sid}/documents        → upload → sanitize → filter → store
  GET    /interviews/{sid}/documents        → list metadata (no payloads)
  GET    /interviews/{sid}/documents/{did}  → full filtered payload (preview)
  DELETE /interviews/{sid}/documents/{did}
  GET    /interviews/{sid}/context-prompt   → preview assembled system prompt
  POST   /interviews/{sid}/chat             → proxy chat to Ollama (NDJSON stream)
  POST   /interviews/{sid}/finalize         → stream final plan from `final_model`
"""
from __future__ import annotations

import json
import math
import re
from ..geocode import short_display
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
        # secure=True,  # enable when serving over HTTPS
    )

from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db import get_db
from ..models import (
    InterviewSession, Location, Service, ServiceAtLocation, SessionDocument,
)
from ..prompt import BASE_SYSTEM_PROMPT, assemble_prompt, render_document
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
from ..tokens import estimate_tokens

router = APIRouter(prefix="/interviews", tags=["interviews"])

# Populated by main.create_app(settings).
_settings: Settings | None = None


def bind_settings(settings: Settings) -> None:
    global _settings
    _settings = settings


def _cfg() -> Settings:
    assert _settings is not None, "bind_settings() not called"
    return _settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo on DateTime(timezone=True). Normalize to UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ── session helpers ───────────────────────────────────────

async def _require_active(
    sid: UUID, request: Request, db: AsyncSession
) -> InterviewSession:
    sess = await db.get(InterviewSession, sid)
    if sess is None:
        raise HTTPException(404, "session not found")
    # The session id is a bearer token; require it to match the visitor's cookie.
    if _read_session_cookie(request) != sid:
        raise HTTPException(404, "session not found")
    if sess.status == "ended":
        raise HTTPException(409, "session has ended")
    now = _now()
    if _aware(sess.expires_at) <= now:
        sess.status = "expired"
        await db.commit()
        raise HTTPException(410, "session expired")
    # Sliding window: every authenticated request extends the idle deadline.
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
        if sess is not None and sess.status == "active" and _aware(sess.expires_at) > now:
            sess.expires_at = now + timedelta(minutes=cfg.session_idle_minutes)
            await db.commit()
            await db.refresh(sess)
            return sess
        # Cookie points at a dead session — delete it and mint a new one.
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
    if _aware(sess.expires_at) <= _now():
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
        # Client picked a candidate from /api/geocode/search — trust it,
        # skip the round-trip to Nominatim.
        lat = payload.lat
        lng = payload.lng
        display_name = (
            payload.short_display_name
            or payload.display_name
            or payload.postal_code
        )
    else:
        # Free-text fallback (Enter without a candidate). Photon handles
        # typos; its response is GeoJSON with flat property fields, so we
        # build the display label inline instead of using short_display().
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

        name        = props.get("name")
        street      = props.get("street")
        housenumber = props.get("housenumber")
        city        = props.get("city")
        postcode    = props.get("postcode")

        # short label: prefer "number street", else name, else street; + city
        short_parts: list[str] = []
        if housenumber and street:
            short_parts.append(f"{housenumber} {street}")
        elif name:
            short_parts.append(name)
        elif street:
            short_parts.append(street)
        if city:
            short_parts.append(city)
        display_name = ", ".join(short_parts) or payload.postal_code

        lat = Decimal(str(lat_f))
        lng = Decimal(str(lon_f))

    
    sess.postal_code = payload.postal_code.strip()
    sess.origin_lat = lat
    sess.origin_lng = lng
    sess.origin_display_name = display_name[:512]

    # Rebuild the index in distance order. Both fields reset together so
    # `[07]` never means a different service before and after a location
    # change.
    rows = await _nearby_services(
        db, lat, lng, cfg.postcode_radius_km,
+       cfg.nearby_location_limit, cfg.nearby_index_limit,
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

    # Forward to the sanitizer. Its _ingest_lock serializes concurrent calls;
    # we make no attempt to serialize at this layer.
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
_DEG_PER_KM = 1.0 / 111.0   # rough; only used to widen the SQL bbox


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
) -> dict[UUID, tuple[Location, float]]:
    """Return {service_id: (closest_location, distance_km)}.

    Mirrors the dedupe rule in `_nearby_services`: if a service is at
    multiple locations, downstream rendering must agree with the location
    the prompt actually listed it under.
    """
    if not service_ids:
        return {}
    loc_rows = (await db.execute(
        select(ServiceAtLocation.service_id, Location)
        .join(Location, Location.id == ServiceAtLocation.location_id)
        .where(ServiceAtLocation.service_id.in_(service_ids))
        .where(Location.latitude.isnot(None), Location.longitude.isnot(None))
    )).all()
    result: dict[UUID, tuple[Location, float]] = {}
    for sal_sid, loc in loc_rows:
        d = _haversine_km(
            origin_lat, origin_lng,
            float(loc.latitude), float(loc.longitude),
        )
        prev = result.get(sal_sid)
        if prev is None or d < prev[1]:
            result[sal_sid] = (loc, d)
    return result

async def _nearby_services(
    db: AsyncSession,
    lat: Decimal,
    lng: Decimal,
    radius_km: float,
    location_limit: int,
    index_limit: int,
) -> list[tuple[Service, Location, float]]:
    """Return (service, location, km) grouped by location, nearest first.

    A service that exists at multiple locations is kept only once, at its
    closest location. The flat list preserves location grouping by order
    — consecutive items share a location — so the prompt renderer does
    not need to group again.

    SQL prefilter is a square bbox (fast, index-friendly); the haversine
    filter and sort happen in Python. The bbox is deliberately generous —
    it only has to be a superset of the true circle.
    """
    lat0, lng0 = float(lat), float(lng)
    deg_pad = radius_km * _DEG_PER_KM
    stmt = (
        select(Service, Location)
        .join(ServiceAtLocation, ServiceAtLocation.service_id == Service.id)
        .join(Location, Location.id == ServiceAtLocation.location_id)
        .where(
            Location.latitude.isnot(None),
            Location.longitude.isnot(None),
            Location.latitude.between(lat0 - deg_pad, lat0 + deg_pad),
            Location.longitude.between(lng0 - deg_pad, lng0 + deg_pad),
            Service.status == "active",
        )
    )
    rows = (await db.execute(stmt)).all()

    # Closest location per service.
    by_service: dict[UUID, tuple[Service, Location, float]] = {}
    for svc, loc in rows:
        if loc.latitude is None or loc.longitude is None:
            continue
        d = _haversine_km(lat0, lng0, float(loc.latitude), float(loc.longitude))
        if d > radius_km:
            continue
        prev = by_service.get(svc.id)
        if prev is None or d < prev[2]:
            by_service[svc.id] = (svc, loc, d)

    # Group by location.
    by_location: dict[UUID, tuple[Location, float, list[Service]]] = {}
    for svc, loc, d in by_service.values():
        entry = by_location.get(loc.id)
        if entry is None:
            by_location[loc.id] = (loc, d, [svc])
        else:
            entry[2].append(svc)

    # Nearest locations first, capped.
    sorted_locs = sorted(by_location.values(), key=lambda t: t[1])[:location_limit]

    # Flatten — services within a location sorted by name for determinism.
    result: list[tuple[Service, Location, float]] = []
    for loc, d, svcs in sorted_locs:
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
    """Placeholder classifier — Service.name only, swapped for a real column later."""
    text = (svc.name or "").lower()
    for cat, keys in _CATEGORY_KEYWORDS.items():
        if any(k in text for k in keys):
            return cat
    first = (svc.name or "").split()
    return first[0].upper() if first else "OTHER"


def _render_service_full(
    idx: int, svc: Service, loc: Location | None, dist_km: float,
) -> str:
    cat = _category_of(svc)
    lines = [f"\n### [{idx:02d}] {cat} — {dist_km:.1f} km", f"**{svc.name}**"]
    if loc:
        addr = loc.address or (
            f"{loc.latitude}, {loc.longitude}"
            if loc.latitude is not None and loc.longitude is not None
            else "(no address)"
        )
        lines.append(f"- Location: {loc.name or '(unnamed)'} — {addr}")
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
    items: list[tuple[int, Service | None, Location | None, float]],
    postal_code: str,
    display_name: str | None,
    revealed: set[int],
) -> str:
    header = f"## Customer location\n{postal_code}"
    if display_name:
        header += f" — {display_name}"
    if not items:
        return header + "\n\nNo services were found near this location."

    lines = [header, "", "## Nearby services"]
    current_loc_id: UUID | None = None
    for idx, svc, loc, dist in items:
        if loc is None:
            # Service row was deleted mid-session; keep the index stable.
            lines.append(f"[{idx:02d}] (no longer available)")
            continue
        if loc.id != current_loc_id:
            if current_loc_id is not None:
                lines.append("")  # blank line between locations
            name = loc.name or "(unnamed location)"
            lines.append(f"{name} ({dist:.1f}km away)")
            if loc.address:
                lines.append(loc.address)
            current_loc_id = loc.id
        lines.append(f"[{idx:02d}] {svc.name if svc else '(unavailable)'}")

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
            idx, svc, loc, d = items[i]
            if svc is None:
                lines.append(f"\n### [{idx:02d}] (no longer available)")
            else:
                lines.append(_render_service_full(idx, svc, loc, d))

    return "\n".join(lines)


def _parse_index(raw) -> int | None:
    """Accept 17, "17", "017", "[17]", "(17)". Out-of-scope → None."""
    if isinstance(raw, bool):  # bool is an int subclass; reject defensively
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
) -> tuple[Location | None, float]:
    origin_lat = float(sess.origin_lat) if sess.origin_lat is not None else 0.0
    origin_lng = float(sess.origin_lng) if sess.origin_lng is not None else 0.0
    hits = await _closest_location_per_service(db, [svc.id], origin_lat, origin_lng)
    return hits.get(svc.id, (None, 0.0))


async def _fetch_nearby_by_ids(
    db: AsyncSession, ids: list[str], sess: InterviewSession,
) -> list[tuple[int, Service | None, Location | None, float]]:
    """Return a list aligned to `ids` (index → service). Missing services are
    kept as `(idx, None, None, 0.0)` so the LLM's index → service mapping
    stays stable even if a row is deleted mid-session.
    """
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

    out: list[tuple[int, Service | None, Location | None, float]] = []
    for idx, u in enumerate(uuids):
        if u is None or u not in services:
            out.append((idx, None, None, 0.0))
            continue
        svc = services[u]
        loc, dist = locs_by_svc.get(u, (None, 0.0))
        out.append((idx, svc, loc, dist))
    return out

def _card_payload(
    idx: int, svc: Service, loc: Location | None, dist_km: float,
) -> dict:
    return {
        "index": idx,
        "service": {
            "id": str(svc.id),
            "name": svc.name,
            "category": _category_of(svc),
            "status": svc.status,
            "distance_km": round(dist_km, 2),
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
    """Returns (tool_text_for_model, card_payload_or_None)."""
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

async def _build_chat_context(
    sid: UUID, db: AsyncSession, base: str = BASE_SYSTEM_PROMPT
):
    """Greedy oldest-first fill; near-by services appended as a block.

    Returns (system_prompt, included, skipped, used_tokens). Skips (does not
    stop at) documents that don't fit, so a large early doc doesn't block a
    smaller later one.
    """
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
    system_prompt = assemble_prompt(base, rendered)

    if sess and sess.origin_lat is not None and sess.origin_lng is not None:
        items = await _fetch_nearby_by_ids(db, sess.nearby_service_ids or [], sess)
        if not items:
            # Index was never built (e.g. session created before this patch, or
            # set_location interrupted). Build it lazily and persist.
            rows = await _nearby_services(
                db, sess.origin_lat, sess.origin_lng,
                cfg.postcode_radius_km,
                cfg.nearby_location_limit, cfg.nearby_index_limit,
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


@router.get("/{sid}/context-prompt", response_model=ContextPromptOut)
async def get_context_prompt(
    sid: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    await _require_active(sid, request, db)
    cfg = _cfg()
    system_prompt, included, skipped, used = await _build_chat_context(sid, db)
    return ContextPromptOut(
        system_prompt=system_prompt,
        included=[DocumentMetaOut.model_validate(d) for d in included],
        skipped=[SkippedDocumentOut(**s) for s in skipped],
        total_tokens=used,
        budget_tokens=cfg.document_budget_tokens,
    )


# ── chat proxy ───────────────────────────────────────────

async def _preflight_ollama(cfg: Settings) -> None:
    """Fail fast if ollama is down, so the client gets a 502 immediately."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as probe:
            await probe.get(f"{cfg.ollama_endpoint}/api/tags")
    except httpx.RequestError as e:
        raise HTTPException(502, f"ollama unreachable: {e}")


def _stream_ollama(cfg: Settings, model: str, messages: list[dict], timeout: float):
    async def stream():
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{cfg.ollama_endpoint}/api/chat",
                json={"model": model, "messages": messages, "stream": True},
            ) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    yield (
                        json.dumps({"error": f"ollama {r.status_code}: {body[:200]!r}"})
                        + "\n"
                    ).encode()
                    return
                async for chunk in r.aiter_raw():
                    yield chunk

    return StreamingResponse(stream(), media_type="application/x-ndjson")

def _err_line(message: str) -> bytes:
    return (json.dumps({"error": message}) + "\n").encode()


def _stream_ollama_with_tools(
    cfg: Settings,
    model: str,
    messages: list[dict],
    tools: list[dict],
    *,
    db: AsyncSession,
    sess: InterviewSession,
    timeout: float,
):
    """Agent loop: content streams to the client unchanged; tool results stay
    server-side. The final answer's history is *not* re-sent next turn — the
    revealed services get promoted into the system prompt by
    `_build_chat_context` instead. That's the workaround for Gemma4's
    tool-feedback quirk.
    """

    async def stream():
        async with httpx.AsyncClient(timeout=timeout) as client:
            for _round in range(MAX_TOOL_ROUNDS):
                tool_calls: list[dict] = []
                assistant_text = ""
                done = False

                async with client.stream(
                    "POST",
                    f"{cfg.ollama_endpoint}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "tools": tools,
                        "stream": True,
                        "options": {"num_ctx": 256_000},
                    },
                ) as r:
                    if r.status_code >= 400:
                        body = await r.aread()
                        yield _err_line(f"ollama {r.status_code}: {body[:200]!r}")
                        return

                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = chunk.get("message", {}) or {}
                        if msg.get("content"):
                            assistant_text += msg["content"]
                            yield (line + "\n").encode()
                        if msg.get("tool_calls"):
                            tool_calls.extend(msg["tool_calls"])
                        if chunk.get("done"):
                            done = True
                            break

                if not tool_calls:
                    return  # normal completion
                if not done:
                    yield _err_line("ollama stream ended before done=true")
                    return

                messages.append({
                    "role": "assistant",
                    "content": assistant_text,
                    "tool_calls": tool_calls,
                })

                emitted_cards: set[int] = set()
                for tc in tool_calls:
                    fn = (tc.get("function") or {}).get("name", "")
                    args = (tc.get("function") or {}).get("arguments") or {}
                    if fn == "get_service_details":
                        text, card = await _execute_get_service_details(
                            args.get("index"), sess, db,
                        )
                        if card is not None and card["index"] not in emitted_cards:
                            emitted_cards.add(card["index"])
                            yield (json.dumps({
                                "event": "service_card",
                                "index": card["index"],
                                "service": card["service"],
                            }) + "\n").encode()
                        messages.append({"role": "tool", "content": text})
                    else:
                        messages.append({
                            "role": "tool",
                            "content": f"unknown tool: {fn}",
                        })
                # loop — ask the model again with the tool results in context

            yield _err_line("tool loop exceeded max rounds")

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
    cfg = _cfg()
    system_prompt, _included, _skipped, _used = await _build_chat_context(sid, db)

    # Client messages are restricted to user/assistant; the system prompt is
    # always ours, so a client-supplied system message would collide.
    messages = [{"role": "system", "content": system_prompt}]
    for m in payload.messages:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})

    await _preflight_ollama(cfg)
    return _stream_ollama_with_tools(
        cfg, cfg.ollama_model, messages, [TOOL_SCHEMA],
        db=db, sess=sess, timeout=cfg.ollama_timeout_s,
    )

# ── final plan ───────────────────────────────────────────

FINALIZE_SYSTEM_PROMPT = (
    "You are a caseworker assistant finalizing an intake. The customer has "
    "finished the conversation and is ready for a concrete plan of action. "
    "Below are their documents, the services near their postal code, and the "
    "conversation so far.\n\n"
    "Produce, in this order:\n"
    "1. A 2–3 sentence summary of the situation.\n"
    "2. Numbered, prioritized next steps (do first → do later).\n"
    "3. Specific referrals to nearby services — cite by name and location, "
    "using ONLY services from the 'Nearby services' list. If none fit, say so.\n"
    "4. Documents to bring and follow-ups to expect.\n\n"
    "Cite document blocks by their `pN_bM` IDs where it strengthens a claim. "
    "Do not invent services, addresses, or eligibility rules. Be concise, "
    "warm, and specific."
)


@router.post("/{sid}/finalize")
async def finalize(
    sid: UUID,
    payload: ChatRequestIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    sess = await _require_active(sid, request, db)
    await _require_located(sess)
    cfg = _cfg()

    system_prompt, _included, _skipped, _used = await _build_chat_context(
        sid, db, base=FINALIZE_SYSTEM_PROMPT
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in payload.messages:
        if m.role in ("user", "assistant"):
            messages.append({"role": m.role, "content": m.content})
    messages.append({
        "role": "user",
        "content": "Please produce the final action plan and referrals now.",
    })

    await _preflight_ollama(cfg)
    return _stream_ollama(cfg, cfg.final_model, messages, cfg.final_timeout_s)