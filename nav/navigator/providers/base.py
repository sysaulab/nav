"""Provider protocol and shared helpers.

A provider is the only object that knows how to talk to one external
directory. It must not:
  - read or write the session, the chat prompt, or the card payload
  - decide which requests it should handle (the registry does)
  - cache anything itself (base.search_with_cache and base.detail_with_cache
    own the cache layer; a provider never sees a cache miss)
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class ProviderError(Exception):
    """Base class. Do not raise directly."""


class ProviderNotFound(ProviderError):
    """The resource is gone at the source."""


class ProviderTransient(ProviderError):
    """5xx, timeout, connection refused — do NOT negative-cache."""


@runtime_checkable
class Provider(Protocol):
    """One external directory.

    `id` is the prefix used in session identifiers and cache paths. It
    must be stable across releases: `"c211-ab"`, not `"c211-alberta"`.
    `regions` names the geographies this provider covers, using the
    same spellings a Photon address carries: "Canada", "Quebec",
    "British Columbia", "Maine", "United States of America". The
    registry normalizes and matches them.
    `priority` breaks ties when two providers register the same region.
    Lower wins. 100 is the default.
    """

    id: str
    label: str
    icon: str
    regions: frozenset[str]
    priority: int
    default_ttl_hours: int
    normalizer_version: int
    attribution_text: str
    attribution_url: str

    async def search(
        self,
        *,
        kind: str,                   # "service" | "location" | "organization"
        q: str | None,
        lat: float,
        lng: float,
        radius_km: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return normalized search results. Empty list is valid."""

    async def detail(
        self, external_id: str,
    ) -> dict[str, Any]:
        """Return the normalized detail payload for one result.

        Raise ProviderNotFound if the source says it is gone; raise
        ProviderTransient if the failure is not a closure signal.
        """

    def portal_url(self, lat: float, lng: float) -> str:
        """Human-facing public search URL for this geography."""


# ── Cache integration ─────────────────────────────────────
#
# The cache lives on the filesystem, keyed by (provider_id, normalizer
# version, hash of the canonical request). A cache entry is opaque to
# the provider — it is just the bytes of `search`/`detail`'s return
# value, JSON-encoded. Providers do not know the cache exists.

def _cache_root() -> Path:
    root = Path.home() / "211cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_path(provider: Provider, kind: str, key: str) -> Path:
    return (
        _cache_root()
        / provider.id
        / f"v{provider.normalizer_version}"
        / kind
        / f"{key}.json"
    )


def cache_read(provider: Provider, kind: str, key: str) -> Any | None:
    path = _cache_path(provider, kind, key)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_bytes())
    except Exception:
        return None  # corrupt entry — treat as miss, will be overwritten


def cache_write(provider: Provider, kind: str, key: str, value: Any) -> None:
    path = _cache_path(provider, kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(
        json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    tmp.replace(path)


async def search_with_cache(
    provider: Provider,
    *,
    kind: str,
    q: str | None,
    lat: float,
    lng: float,
    radius_km: float,
    limit: int,
) -> list[dict[str, Any]]:
    canonical = {
        "kind": kind,
        "q": q,
        "lat": round(lat, 4),       # ~11 m precision — sub-lot, above cache-noise
        "lng": round(lng, 4),
        "radius_km": radius_km,
        "limit": limit,
    }
    key = _cache_key(canonical)
    cached = cache_read(provider, "search", key)
    if cached is not None:
        return cached
    result = await provider.search(**canonical)
    cache_write(provider, "search", key, result)
    return result


async def detail_with_cache(
    provider: Provider, external_id: str,
) -> dict[str, Any]:
    key = _cache_key({"external_id": external_id})
    cached = cache_read(provider, "detail", key)
    if cached is not None:
        return cached
    result = await provider.detail(external_id)
    cache_write(provider, "detail", key, result)
    return result