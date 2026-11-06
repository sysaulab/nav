"""Built-in provider that answers from the local HSDS database.

The local provider always resolves: it is the fallback when no
external provider matches a region, and the only source of the
operator's own supplement. It is not registered by region — the
loader calls register_default for it.

It does NOT use the filesystem cache: the source is a local query,
so caching would add staleness with no network cost saved.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from ..db import get_sessionmaker
from ..models import Location, Service, ServiceAtLocation
from .base import ProviderNotFound


class LocalProvider:
    id = "local"
    label = "local"
    icon = "📍"
    regions: frozenset[str] = frozenset()
    priority = 0
    default_ttl_hours = 0           # unused; no cache
    normalizer_version = 1
    attribution_text = "Added by the operator"
    attribution_url = ""

    async def search(
        self,
        *,
        kind: str,
        q: str | None,
        lat: float,
        lng: float,
        radius_km: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        if kind != "service":
            return []  # local supplement is service-shaped only for now

        async with get_sessionmaker()() as db:
            stmt = (
                select(Service, Location)
                .join(ServiceAtLocation, ServiceAtLocation.service_id == Service.id)
                .join(Location, Location.id == ServiceAtLocation.location_id)
                .where(Service.status == "active")
            )
            if q:
                stmt = stmt.where(Service.name.ilike(f"%{q}%"))
            rows = (await db.execute(stmt)).all()

        # Let the caller (registry / chat) do distance filtering; local
        # sets are small, so a straight return is cheaper than a bbox.
        out: list[dict[str, Any]] = []
        for svc, loc in rows[:limit]:
            out.append({
                "external_id": str(svc.id),
                "name": svc.name,
                "description": svc.description,
                "location_name": loc.name,
                "address": loc.address,
                "latitude": float(loc.latitude) if loc.latitude is not None else None,
                "longitude": float(loc.longitude) if loc.longitude is not None else None,
            })
        return out

    async def detail(self, external_id: str) -> dict[str, Any]:
        try:
            svc_id = uuid.UUID(external_id)
        except ValueError:
            raise ProviderNotFound(f"invalid local id: {external_id}")

        async with get_sessionmaker()() as db:
            svc = await db.get(Service, svc_id)
            if svc is None:
                raise ProviderNotFound(f"service {external_id} not found")
            return {
                "external_id": external_id,
                "name": svc.name,
                "description": svc.description,
                "eligibility_description": svc.eligibility_description,
                "application_process": svc.application_process,
                "fees_description": svc.fees_description,
                "email": svc.email,
                "url": svc.url,
                "status": svc.status,
            }

    def portal_url(self, lat: float, lng: float) -> str:
        return ""  # local has no portal


PROVIDER = LocalProvider()