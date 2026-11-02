import argparse
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import logging

from .geocode import short_display 

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import delete as sa_delete, select

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
    async with get_sessionmaker()() as db:
        rows = (await db.execute(
            select(InterviewSession.id, InterviewSession.expires_at)
        )).all()
        expired = [row[0] for row in rows if _aware(row[1]) <= now]
        if expired:
            await db.execute(
                sa_delete(InterviewSession).where(InterviewSession.id.in_(expired))
            )
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
        endpoint = settings.nominatim_endpoint.rstrip("/")
        try:
            code, _ = await _http_get(f"{endpoint}/", timeout=2.0)
            return {"ok": True, "status_code": code, "endpoint": endpoint}
        except Exception as e:
            return {"ok": False, "endpoint": endpoint, "error": str(e)}

    @app.get("/api/geocode")
    async def geocode(
        q: str = Query(..., min_length=1, description="Free-form address"),
    ):
        endpoint = settings.nominatim_endpoint.rstrip("/")
        params = urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
        try:
            code, body = await _http_get(f"{endpoint}/search?{params}", timeout=5.0)
        except Exception as e:
            raise HTTPException(502, f"geocoder unreachable: {e}")
        if code >= 400:
            raise HTTPException(502, f"geocoder returned {code}")
        results = json.loads(body)
        if not results:
            return None
        top = results[0]
        return {
            "lat": float(top["lat"]),
            "lng": float(top["lon"]),
            "display_name": top.get("display_name"),
        }

    @app.get("/api/geocode/search")
    async def geocode_search(
        q: str = Query(..., min_length=2, description="Address or postal code"),
        limit: int = Query(5, ge=1, le=10),
    ):
        """Autocomplete candidates. Each result carries a compact
        `short_display_name` alongside the full Nominatim display string."""
        endpoint = settings.nominatim_endpoint.rstrip("/")
        params = urllib.parse.urlencode(
            {
                "q": q,
                "format": "json",
                "limit": limit,
                "addressdetails": 1,
            }
        )
        try:
            code, body = await _http_get(f"{endpoint}/search?{params}", timeout=5.0)
        except Exception as e:
            raise HTTPException(502, f"geocoder unreachable: {e}")
        if code >= 400:
            raise HTTPException(502, f"geocoder returned {code}")
        results = json.loads(body)
        out: list[dict] = []
        for r in results:
            addr = r.get("address") or {}
            full = r.get("display_name") or ""
            out.append(
                {
                    "lat": float(r["lat"]),
                    "lng": float(r["lon"]),
                    "display_name": full,
                    "short_display_name": short_display(addr, full),
                    "postcode": addr.get("postcode"),
                    "city": addr.get("city")
                    or addr.get("town")
                    or addr.get("village"),
                }
            )
        return out
    
# Remove the early duplicate entirely.

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "service": "maestro",
            "version": app.version,
            "sanitizer": settings.sanitizer_endpoint,
            "geocoder": settings.nominatim_endpoint,
            "ollama": settings.ollama_endpoint,
            "model": settings.ollama_model,
        }

    @app.get("/api/health/ingest")
    async def health_ingest():
        endpoint = settings.sanitizer_endpoint
        try:
            code, _ = await _http_get(endpoint, timeout=5.0)   # match upload's patience
            return {"ok": 200 <= code < 500, "status_code": code, "endpoint": endpoint}
        except Exception as e:
            return {"ok": False, "endpoint": endpoint, "error": str(e)}

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
    parser.add_argument("--nominatim-endpoint", default=None)
    args = parser.parse_args()

    overrides = {}
    if args.db_url:
        overrides["database_url"] = args.db_url
    if args.ingest_server_endpoint:
        overrides["ingest_server_endpoint"] = args.ingest_server_endpoint
    if args.nominatim_endpoint:
        overrides["nominatim_endpoint"] = args.nominatim_endpoint
    settings = Settings().model_copy(update=overrides)

    uvicorn.run(create_app(settings), host=args.host, port=args.port)