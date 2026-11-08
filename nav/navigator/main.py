import argparse
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import logging

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import delete as sa_delete, select, text

from .config import Settings
from .db import get_engine, get_sessionmaker, init_engine
from .models import Base, InterviewSession
from .ai.registry import reload_registry
from .routers import (
    admin,
    exports,
    interviews,
    locations,
    nested,
    organizations,
    service_at_location,
    services,
)
from .geocode import photon_display_name





log = logging.getLogger("navigator")

async def _purge_expired_sessions() -> int:
    now = datetime.now(timezone.utc)

    async with get_sessionmaker()() as db:
        # Postgres advisory lock: exactly one replica purges per tick.
        # A replica that crashes mid-purge releases the lock on rollback.
        got = (await db.execute(
            text("SELECT pg_try_advisory_xact_lock(920111)")
        )).scalar()
        if not got:
            return 0

        rows = (await db.execute(
            select(InterviewSession.id, InterviewSession.expires_at)
        )).all()
        expired = [row[0] for row in rows if row[1] <= now]
        if expired:
            await db.execute(
                sa_delete(InterviewSession).where(InterviewSession.id.in_(expired))
            )
        # Commit unconditionally: this is what releases the advisory
        # lock, even when there was nothing to delete.
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
    admin.bind_settings(settings)

    app = FastAPI(title="Local Resource Navigator", version="0.2.0")

    @app.on_event("startup")
    async def _create_schema():
        engine = get_engine()
        async with engine.begin() as conn:
            # Postgres: serialize schema creation across replicas.
            # pg_advisory_xact_lock releases on commit, so a crashed
            # replica cannot leave the lock held. The key is arbitrary
            # but must be identical on every replica.
            await conn.execute(text("SELECT pg_advisory_xact_lock(920110)"))
            await conn.run_sync(Base.metadata.create_all)

        # Populate the model registry (hardcoded -> env -> DB).
        # Admin routes refresh this after every write, so this only
        # runs at process start.
        async with get_sessionmaker()() as db:
            await reload_registry(db, settings)

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

        return {
            "lat": lat,
            "lng": lon,
            "display_name": photon_display_name(props) or q,
        }
    
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

    @app.get("/api/health/sql")
    async def health_sql():
        """Probe the database with a trivial SELECT 1.

        Reports the backend name so the SQL pill can show which engine is
        in play. Uses the same async engine the pipeline uses, so a healthy
        signal here means the routes will actually be able to talk to the DB.

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
        # /ingest only accepts POST — a GET returns 405, which a "200..500"
        # check would count as reachable without ever validating that the
        # sanitizer actually answers on the endpoint we're about to POST to.
        parts = urllib.parse.urlsplit(endpoint)
        health_url = urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, "/health", "", "")
        )

        try:
            code, _ = await _http_get(health_url, timeout=5.0)
            return {
                "ok": code == 200,
                "status_code": code,
                "endpoint": endpoint,
                "health_url": health_url,
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

    # Public discovery surface only. Directory management moved to
    # /admin-api (nav-admin UI). Nothing under /api touches the org/
    # loc/svc tables anymore.
    for r in (
        interviews.router,
        exports.router,
    ):
        app.include_router(r, prefix="/api")

    app.include_router(admin.router)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="navigator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--ingest-server-endpoint", default=None)
    parser.add_argument("--photon-endpoint", default=None)
    args = parser.parse_args()

    # Pass CLI overrides as kwargs to Settings() rather than .model_copy().
    # database_url is a required field, so Settings() with no env var raises
    # before a post-construction copy could supply it.
    overrides: dict = {}
    if args.db_url:
        overrides["database_url"] = args.db_url
    if args.ingest_server_endpoint:
        overrides["sanitizer_endpoint"] = args.ingest_server_endpoint
    if args.photon_endpoint:
        overrides["photon_endpoint"] = args.photon_endpoint
    settings = Settings(**overrides)

    uvicorn.run(create_app(settings), host=args.host, port=args.port)