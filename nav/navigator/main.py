import argparse
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import logging

# from .geocode import short_display 

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import delete as sa_delete, select, text

from .config import Settings
from .db import get_engine, get_sessionmaker, init_engine
from .models import Base, InterviewSession
from .routers import (
    exports,
    interviews,
    locations,
    nested,
    organizations,
    service_at_location,
    services,
)

log = logging.getLogger("navigator")

async def _purge_expired_sessions() -> int:
    now = datetime.now(timezone.utc)
    engine = get_engine()
    is_postgres = engine.url.get_backend_name() == "postgresql"

    async with get_sessionmaker()() as db:
        # Postgres: exactly one replica purges per tick. A replica
        # that crashes mid-purge releases the lock on rollback.
        # SQLite: no lock — the existing path already runs on a
        # single process.
        if is_postgres:
            got = (await db.execute(
                text("SELECT pg_try_advisory_xact_lock(920111)")
            )).scalar()
            if not got:
                return 0

        rows = (await db.execute(
            select(InterviewSession.id, InterviewSession.expires_at)
        )).all()
        expired = [row[0] for row in rows if _aware(row[1]) <= now]
        if expired:
            await db.execute(
                sa_delete(InterviewSession).where(InterviewSession.id.in_(expired))
            )
        # Commit unconditionally: on Postgres this is what releases
        # the advisory lock, even when there was nothing to delete.
        await db.commit()
    return len(expired)


async def _purge_loop(interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            n = await _purge_expired_sessions()
            if n:
                log.info("purged %d expired interview session(s)", n)
        except Exception:
            log.exception("session purge failed")

def _aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo on DateTime(timezone=True). Normalize to UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _http_get(url: str, timeout: float = 2.0) -> tuple[int, bytes]:
    """GET via urllib, off the event loop. Never raises on HTTPError — returns the code."""

    def _do() -> tuple[int, bytes]:
        req = urllib.request.Request(
            url, headers={"User-Agent": "local-resource-navigator/0.1"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    return await asyncio.to_thread(_do)


def create_app(settings: Settings) -> FastAPI:
    init_engine(settings)
    interviews.bind_settings(settings)

    app = FastAPI(title="Local Resource Navigator", version="0.1.0")

    @app.on_event("startup")
    async def _create_schema():
        engine = get_engine()
        async with engine.begin() as conn:
            # Postgres: serialize schema creation across replicas.
            # pg_advisory_xact_lock releases on commit, so a crashed
            # replica cannot leave the lock held. The key is arbitrary
            # but must be identical on every replica.
            if not settings.database_url.startswith("sqlite"):
                await conn.execute(text("SELECT pg_advisory_xact_lock(920110)"))

            await conn.run_sync(Base.metadata.create_all)

            # SQLite can't add columns via create_all; patch in `address` if missing.
            # Patch-in columns that `create_all` can't add to existing SQLite DBs.
            if settings.database_url.startswith("sqlite"):
                async def _add_if_missing(table: str, column: str, ddl: str) -> None:
                    result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
                    cols = {row[1] for row in result.fetchall()}
                    if column not in cols:
                        await conn.exec_driver_sql(ddl)

                await _add_if_missing("location", "address",
                    "ALTER TABLE location ADD COLUMN address VARCHAR(1024)")

                await _add_if_missing("interview_session", "postal_code",
                    "ALTER TABLE interview_session ADD COLUMN postal_code VARCHAR(32)")
                await _add_if_missing("interview_session", "origin_lat",
                    "ALTER TABLE interview_session ADD COLUMN origin_lat NUMERIC(9, 6)")
                await _add_if_missing("interview_session", "origin_lng",
                    "ALTER TABLE interview_session ADD COLUMN origin_lng NUMERIC(9, 6)")
                await _add_if_missing("interview_session", "origin_display_name",
                    "ALTER TABLE interview_session ADD COLUMN origin_display_name VARCHAR(512)")
                await _add_if_missing("interview_session", "nearby_service_ids",
                    "ALTER TABLE interview_session ADD COLUMN nearby_service_ids JSON")
                await _add_if_missing("interview_session", "revealed_service_indices",
                    "ALTER TABLE interview_session ADD COLUMN revealed_service_indices JSON")

        # One-time sweep at startup so restarts don't leave orphans lying around.
        purged = await _purge_expired_sessions()
        if purged:
            log.info("startup: purged %d expired interview session(s)", purged)

        # Continuous sweep: with per-visitor sessions and a 15-minute idle
        # TTL, sessions expire silently between requests, so a background
        # task is what actually reclaims them.
        app.state.purger = asyncio.create_task(
            _purge_loop(settings.session_purge_interval_s)
        )

    @app.on_event("shutdown")
    async def _stop_purger():
        task = getattr(app.state, "purger", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            app.state.purger = None



    @app.get("/api/health/geocoder")
    async def health_geocoder():
        endpoint = settings.photon_endpoint.rstrip("/")
        # Probe the real search endpoint, not the server root — a root "/"
        # can return 200 while the index is still warming up, giving a
        # green pill on a broken geocoder. A tiny real query exercises
        # the index and the JSON pipeline.
        probe_url = f"{endpoint}/api?q=a&limit=1"
        try:
            code, _ = await _http_get(probe_url, timeout=3.0)
            return {
                "ok": 200 <= code < 300,
                "status_code": code,
                "endpoint": endpoint,
            }
        except Exception as e:
            return {"ok": False, "endpoint": endpoint, "error": str(e)}

        
    @app.get("/api/geocode")
    async def geocode(
        q: str = Query(..., min_length=1, description="Free-form address"),
    ):
        endpoint = settings.photon_endpoint.rstrip("/")
        params = urllib.parse.urlencode({"q": q, "limit": 1, "lang": "en"})
        try:
            code, body = await _http_get(f"{endpoint}/api?{params}", timeout=5.0)
        except Exception as e:
            raise HTTPException(502, f"photon unreachable: {e}")
        if code >= 400:
            raise HTTPException(502, f"photon returned {code}")

        try:
            data = json.loads(body)
        except ValueError as e:
            raise HTTPException(502, f"photon returned non-JSON: {e}")

        features = data.get("features") or []
        if not features:
            return None

        feat = features[0]
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            return None
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError):
            return None

        # Photon has no `display_name` — build one from flat fields.
        # Order matches what Nominatim would have returned closely enough
        # for the "Matched: …" note in Database.tsx.
        parts: list[str] = []
        if props.get("name"):
            parts.append(props["name"])
        if props.get("street"):
            hn = props.get("housenumber")
            parts.append(f"{hn} {props['street']}".strip() if hn else props["street"])
        if props.get("city"):
            parts.append(props["city"])
        if props.get("state"):
            parts.append(props["state"])
        if props.get("country"):
            parts.append(props["country"])
        display_name = ", ".join(parts) or q

        return {"lat": lat, "lng": lon, "display_name": display_name}

    
    @app.get("/api/geocode/search")
    async def geocode_search(
        q: str = Query(..., min_length=2, description="Address, place, or postal code"),
        limit: int = Query(5, ge=1, le=10),
    ):
        """Fuzzy autocomplete via Photon.

        Response shape matches GeocodeSuggestion in nav-ui/src/types.ts
        exactly, so LocationGate and any other caller are unchanged.
        """
        endpoint = settings.photon_endpoint.rstrip("/")
        params = urllib.parse.urlencode({"q": q, "limit": limit, "lang": "en"})
        try:
            code, body = await _http_get(f"{endpoint}/api?{params}", timeout=4.0)
        except Exception as e:
            raise HTTPException(502, f"photon unreachable: {e}")
        if code >= 400:
            raise HTTPException(502, f"photon returned {code}")

        try:
            data = json.loads(body)
        except ValueError as e:
            raise HTTPException(502, f"photon returned non-JSON: {e}")

        out: list[dict] = []
        for feat in data.get("features", [])[:limit]:
            props = feat.get("properties") or {}
            coords = (feat.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                continue

            name        = props.get("name")
            street      = props.get("street")
            housenumber = props.get("housenumber")
            city        = props.get("city")
            postcode    = props.get("postcode")
            state       = props.get("state")
            country     = props.get("country")

            street_full = (
                f"{housenumber} {street}".strip()
                if housenumber and street else street
            )

            # ── short label: what fits on one line in the dropdown ──
            short_parts: list[str] = []
            if name:
                short_parts.append(name)
            elif street_full:
                short_parts.append(street_full)
            elif postcode:
                short_parts.append(postcode)
            if city and city not in short_parts:
                short_parts.append(city)
            short_display_name = ", ".join(short_parts) or q

            # ── full label: everything, in address order, deduped ──
            full_parts: list[str] = []
            if name and name not in (street_full, city):
                full_parts.append(name)
            if street_full:
                full_parts.append(street_full)
            if city:
                full_parts.append(city)
            if postcode:
                full_parts.append(postcode)
            if state:
                full_parts.append(state)
            if country:
                full_parts.append(country)

            seen: list[str] = []
            for p in full_parts:
                if not seen or seen[-1] != p:
                    seen.append(p)
            display_name = ", ".join(seen) or short_display_name

            out.append({
                "lat": lat,
                "lng": lon,
                "display_name": display_name,
                "short_display_name": short_display_name[:120],
                "postcode": postcode,
                "city": city,
            })

        return out    


    @app.get("/api/health/sql")
    async def health_sql():
        """Probe the database with a trivial SELECT 1.

        Reports the backend name (postgresql / sqlite) so the SQL pill
        can show which engine is in play. Uses the same async engine the
        pipeline uses, so a healthy signal here means the routes will
        actually be able to talk to the DB.

        SELECT 1 rather than the advisory-lock probe used by the purge
        loop: advisory locks serialize against in-flight ingest, which
        would make the health check lie under load.
        """
        engine = get_engine()
        backend = engine.url.get_backend_name()
        try:
            async with get_sessionmaker()() as db:
                await db.execute(text("SELECT 1"))
            return {"ok": True, "backend": backend}
        except Exception as e:
            return {"ok": False, "backend": backend, "error": str(e)}



    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "service": "maestro",
            "version": app.version,
            "sanitizer": settings.sanitizer_endpoint,
            "geocoder": settings.photon_endpoint,
            "ollama": settings.ollama_endpoint,
            "model": settings.ollama_model,
        }

    @app.get("/api/health/ingest")
    async def health_ingest():
        endpoint = settings.sanitizer_endpoint

        # Probe the sanitizer's /health route, not its /ingest route.
        #
        # /ingest only accepts POST — a GET returns 405, which the old
        # `200 <= code < 500` check happily counted as "reachable" without
        # ever validating that the sanitizer actually answers on the
        # endpoint we're about to POST uploads to. Deriving /health here
        # gives a real 200-vs-non-200 signal.
        #
        # urlunsplit/urlsplit (rather than string surgery) so it works
        # regardless of how the env var was written — /ingest, /ingest/,
        # /api/ingest, or bare host:port.
        parts = urllib.parse.urlsplit(endpoint)
        health_url = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, "/health", "", "")
        )

        try:
            code, _ = await _http_get(health_url, timeout=5.0)
            return {
                "ok": code == 200,
                "status_code": code,
                "endpoint": endpoint,      # the POST target — what the UI shows
                "health_url": health_url,  # what was actually probed
            }
        except Exception as e:
            return {
                "ok": False,
                "endpoint": endpoint,
                "health_url": health_url,
                "error": str(e),
            }

    @app.get("/api/health/ollama")
    async def health_ollama():
        endpoint = settings.ollama_endpoint.rstrip("/")
        try:
            code, _ = await _http_get(f"{endpoint}/api/tags", timeout=2.0)
            return {
                "ok": 200 <= code < 300,
                "status_code": code,
                "endpoint": endpoint,
                "model": settings.ollama_model,
            }
        except Exception as e:
            return {
                "ok": False,
                "endpoint": endpoint,
                "model": settings.ollama_model,
                "error": str(e),
            }
        
    for r in (
        organizations.router,
        locations.router,
        services.router,
        service_at_location.router,
        nested.router,
        interviews.router,
        exports.router,
    ):
        app.include_router(r, prefix="/api")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="navigator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--ingest-server-endpoint", default=None)
    parser.add_argument("--photon-endpoint", default=None)
    args = parser.parse_args()

    overrides = {}
    if args.db_url:
        overrides["database_url"] = args.db_url
    if args.ingest_server_endpoint:
        overrides["sanitizer_endpoint"] = args.ingest_server_endpoint
    if args.photon_endpoint:
        overrides["photon_endpoint"] = args.photon_endpoint
    settings = Settings().model_copy(update=overrides)

    uvicorn.run(create_app(settings), host=args.host, port=args.port)