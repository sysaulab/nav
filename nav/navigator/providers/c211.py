"""Connect 211 provider (skeleton).

Replace `search` and `detail` with calls to c211's HSDA endpoints
once the request/response shapes are confirmed. The interface is
fixed; only the bodies are stubs here.

Register one instance per province. c211 serves provincial data
under distinct endpoints, so each instance has its own id and
regions set. A shared base class holds the common plumbing.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from .base import ProviderNotFound, ProviderTransient


class C211Provider:
    """Shared code. Concrete instances override `regions` and `id`."""

    label = "211"
    icon = "🍁"
    priority = 100
    default_ttl_hours = 24
    normalizer_version = 1
    attribution_text = "211"
    attribution_url = "https://211.ca"

    id: str
    regions: frozenset[str]

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _client_or_raise(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={"Accept": "application/json"},
            )
        return self._client

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
        client = await self._client_or_raise()
        params = {
            "lat": lat,
            "lng": lng,
            "radius_km": radius_km,
            "limit": limit,
        }
        if q:
            params["q"] = q
        try:
            r = await client.get(
                f"{self._base_url()}/search/{kind}", params=params,
            )
        except httpx.RequestError as e:
            raise ProviderTransient(str(e))
        if r.status_code == 404:
            return []
        if r.status_code >= 500:
            raise ProviderTransient(f"c211 {r.status_code}")
        if r.status_code >= 400:
            raise ProviderTransient(f"c211 {r.status_code}: {r.text[:120]}")

        # TODO: normalize c211's shape to this contract.
        # Returned dicts must contain at least:
        #   external_id, name, description,
        #   location_name, address, latitude, longitude
        return r.json().get("results", [])

    async def detail(self, external_id: str) -> dict[str, Any]:
        client = await self._client_or_raise()
        try:
            r = await client.get(f"{self._base_url()}/detail/{external_id}")
        except httpx.RequestError as e:
            raise ProviderTransient(str(e))
        if r.status_code == 404:
            raise ProviderNotFound(f"{self.id}: {external_id}")
        if r.status_code >= 500:
            raise ProviderTransient(f"c211 {r.status_code}")
        # TODO: normalize
        return r.json()

    def portal_url(self, lat: float, lng: float) -> str:
        return f"https://211.ca/search?lat={lat}&lng={lng}"

    def _base_url(self) -> str:
        return self._settings.c211_base_url


# One instance per province. Each is a class so `id` and `regions`
# are distinct per registration.
class _C211Alberta(C211Provider):
    id = "c211-ab"
    regions = frozenset({"Alberta", "Canada"})


class _C211BritishColumbia(C211Provider):
    id = "c211-bc"
    regions = frozenset({"British Columbia", "Canada"})


class _C211Quebec(C211Provider):
    id = "c211-qc"
    regions = frozenset({"Quebec", "Canada"})


# Register the instances the deployment actually enables. A config
# file or env var could gate this later; for now the loader sees
# exactly the PROVIDER it defines.
PROVIDER = _C211Alberta(__import__("navigator.config", fromlist=["Settings"]).Settings())