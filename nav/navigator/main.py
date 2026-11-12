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
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .config import Settings
from .db import get_engine, get_sessionmaker, init_engine
from .models import (
    Base,
    InterviewSession,
    TranslationJob,
    UiString,
    UiStringTranslation,
)
from .ai.registry import reload_registry
from .runtime import reload_runtime
from .translator import run_translation_job, seed_missing_english
from .ui_strings import CONTEXTS, ENGLISH_STRINGS
from .routers import (
    admin,
    exports,
    interviews,
    locations,
    nested,
    organizations,
    service_at_location,
    services,
    ui as ui_router,
)
from .geocode import photon_display_name


log = logging.getLogger("navigator")


async def _purge_expired_sessions() -> int:
    now = datetime.now(timezone.utc)

    async with get_sessionmaker()() as db:
        # Postgres advisory lock: exactly one replica purges per tick.
        got = (await db.execute(
            text("SELECT pg_try_advisory_xact_lock(920111)")
        )).scalar()
        if not got:
            return 0

        deleted_ids = (await db.execute(
            sa_delete(InterviewSession)
            .where(InterviewSession.expires_at <= now)
            .returning(InterviewSession.id)
        )).scalars().all()

        await db.commit()

    return len(deleted_ids)


async def _purge_loop(interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            n = await _purge_expired_sessions()
            if n:
                log.info("purged %d expired interview session(s)", n)
        except Exception:
            log.exception("session purge failed")


async def _sync_ui_strings(db) -> None:
    """Reconcile the database with the English dictionary.

    The dictionary in ui_strings.py is the source of truth. Two things
    happen on startup:

      1. Keys present in the dictionary but absent from the DB are
         inserted. This is how a new string gets its first English row.

      2. Keys whose English text has changed are updated, and every
         existing translation for that key is deleted. A translation
         of stale English is worse than a missing translation: the
         missing one shows an empty cell (honest); the stale one shows
         text that no longer matches the UI (silently wrong).

    Concurrency-safe across replicas booting simultaneously against a
    shared Postgres. The `added` branch uses INSERT ... ON CONFLICT
    DO NOTHING: N replicas racing to seed the same key all execute the
    same statement, exactly one wins the primary key, the rest are
    no-ops, and no replica aborts on IntegrityError. The `updated`
    branch was already safe — every replica computes the same new
    English from the same source dictionary and writes it, so the
    final value is identical regardless of interleaving.

    Idempotent. Running on every boot is cheap (one SELECT, a few
    writes only when the dictionary actually changed).
    """
    current = {
        row.key: row
        for row in (await db.execute(select(UiString))).scalars()
    }
    added = updated = 0
    for key, english in ENGLISH_STRINGS.items():
        if key not in current:
            inserted = (await db.execute(
                pg_insert(UiString)
                .values(key=key, english=english, context=CONTEXTS.get(key))
                .on_conflict_do_nothing(index_elements=["key"])
                .returning(UiString.key)
            )).scalar()
            if inserted:
                added += 1
        elif current[key].english != english:
            await db.execute(
                sa_delete(UiStringTranslation).where(
                    UiStringTranslation.key == key,
                )
            )
            current[key].english = english
            current[key].context = CONTEXTS.get(key)
            updated += 1
    await db.commit()
    if added or updated:
        log.info(
            "ui_strings.synced added=%d updated=%d (translations invalidated)",
            added, updated,
        )

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
            await conn.execute(text("SELECT pg_advisory_xact_lock(920110)"))
            await conn.run_sync(Base.metadata.create_all)

        # Reconcile the English UI dictionary, then populate the runtime
        # registries. Ordering matters: _sync_ui_strings must run before
        # any handler that might read UiString.
        async with get_sessionmaker()() as db:
            await _sync_ui_strings(db)
            await reload_registry(db, settings)
            await reload_runtime(db, settings)

        # Resume any translation jobs a dying replica left pending. The
        # admin route fired asyncio.create_task when the job was created;
        # if that process died before completion, the job sits at
        # status=pending (or =running with a stale heartbeat). Either way,
        # any replica can pick it up.
        async with get_sessionmaker()() as db:
            pending = (await db.execute(
                select(TranslationJob.id).where(
                    TranslationJob.status.in_(["pending", "running"])
                )
            )).scalars().all()
        for job_id in pending:
            log.info("translations.resume job_id=%s", job_id)
            asyncio.create_task(run_translation_job(job_id))

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
        """Fuzzy autocomplete via Photon."""
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
        ui_router.router,
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

    overrides: dict = {}
    if args.db_url:
        overrides["database_url"] = args.db_url
    if args.ingest_server_endpoint:
        overrides["sanitizer_endpoint"] = args.ingest_server_endpoint
    if args.photon_endpoint:
        overrides["photon_endpoint"] = args.photon_endpoint
    settings = Settings(**overrides)

    uvicorn.run(create_app(settings), host=args.host, port=args.port)