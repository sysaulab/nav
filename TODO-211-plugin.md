## Design summary

A provider is a small async class that knows how to talk to one directory and which named regions it covers. The registry matches an address's region chain against those claims, most-specific first. The chat flow (set_location, get_service_details) goes through the registry; the database search page bypasses it entirely because it is a local-supplement browser. Identifiers on the session become `"<provider_id>:<external_id>"` so the detail call routes back to the same provider that produced the result.

## File layout

```
nav/navigator/providers/
  __init__.py        exports Provider, get_registry
  base.py            Protocol, canonical request, cache read/write
  registry.py        registration, region matching, directory scan
  regions.py         Photon address → normalized region chain
  local.py           built-in reference provider (queries local DB)
  c211.py            example external provider (skeleton)
  ndp.py             (later)
```

The loader is a directory scan. Every `.py` file that defines a module-level `PROVIDER = <ProviderClass>()` is instantiated at startup. A new connector is a new file, no packaging, no entry points.

## `providers/base.py`

```python
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
```

## `providers/regions.py`

```python
"""Resolve a Photon address response to a normalized region chain.

A Photon `properties` dict carries `country`, `state`, and sometimes
`province`. The chain is most-specific first: [state, country].
A provider that registers "Quebec" matches a Quebec address before
one that registers "Canada".
"""
from __future__ import annotations

import re
import unicodedata


# Abbreviations the geocoder may return. Any new alias is one line.
_REGION_ALIASES: dict[str, str] = {
    "united states": "united states of america",
    "usa": "united states of america",
    "us": "united states of america",
    "uk": "united kingdom",
    "great britain": "united kingdom",
}


def normalize_region(name: str) -> str:
    """Case-, accent-, and punctuation-insensitive region key."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[-_]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _REGION_ALIASES.get(s, s)


def region_chain(address: dict | None) -> list[str]:
    """Return [state_or_province, country] with normalization.

    Either element may be absent; the list shrinks accordingly.
    Empty list means "unknown" — the caller falls back to the
    default provider.
    """
    if not address:
        return []
    chain: list[str] = []
    state = address.get("state") or address.get("province")
    if state:
        chain.append(normalize_region(str(state)))
    country = address.get("country")
    if country:
        chain.append(normalize_region(str(country)))
    return chain
```

## `providers/registry.py`

```python
"""Provider registry and region-based dispatch.

Load order:
  1. every `providers/*.py` file with a module-level PROVIDER is imported
  2. each PROVIDER is validated (id, regions, priority)
  3. regions are normalized and indexed

The registry resolves a request by walking the region chain from
most-specific to least. First provider registered for the first
matching region wins. Ties are broken by priority (lower wins).
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

from .base import Provider
from .regions import normalize_region

log = logging.getLogger("navigator.providers")


class RegistryError(Exception):
    pass


class ProviderRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, Provider] = {}
        self._by_region: dict[str, list[Provider]] = {}
        self._default: Provider | None = None

    # ── registration ─────────────────────────────────────

    def register(self, provider: Provider) -> None:
        if provider.id in self._by_id:
            raise RegistryError(f"duplicate provider id: {provider.id}")
        if not provider.regions and provider.id != "local":
            raise RegistryError(
                f"provider {provider.id} registered no regions "
                f"(only the built-in `local` provider may claim none)"
            )
        self._by_id[provider.id] = provider
        for raw in provider.regions:
            key = normalize_region(raw)
            self._by_region.setdefault(key, []).append(provider)
        # Sort each bucket by priority (lower first) so resolve()
        # does not need to sort on every call.
        for bucket in self._by_region.values():
            bucket.sort(key=lambda p: p.priority)
        log.info(
            "provider.registered id=%s regions=%s priority=%d",
            provider.id, sorted(provider.regions), provider.priority,
        )

    def register_default(self, provider: Provider) -> None:
        self._default = provider
        self._by_id[provider.id] = provider
        log.info("provider.default id=%s", provider.id)

    # ── dispatch ─────────────────────────────────────────

    def resolve(self, chain: list[str]) -> Provider | None:
        """Most specific region first. Falls back to default."""
        for region in chain:
            bucket = self._by_region.get(region)
            if bucket:
                return bucket[0]
        return self._default

    def get(self, provider_id: str) -> Provider | None:
        return self._by_id.get(provider_id)

    def all(self) -> list[Provider]:
        return list(self._by_id.values())


# ── module-level singleton ────────────────────────────────

_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def load_builtin_providers(package: str = "navigator.providers") -> None:
    """Import every module in `providers/` and register its PROVIDER."""
    registry = get_registry()
    pkg_path = Path(importlib.import_module(package).__file__).parent
    for path in sorted(pkg_path.glob("*.py")):
        name = path.stem
        if name in {"__init__", "base", "registry", "regions"}:
            continue
        mod = importlib.import_module(f"{package}.{name}")
        provider = getattr(mod, "PROVIDER", None)
        if provider is None:
            continue
        if getattr(provider, "regions", None) is None:
            registry.register_default(provider)
        else:
            registry.register(provider)
```

## `providers/local.py` — reference implementation

```python
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
```

## `providers/c211.py` — external skeleton

```python
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
```

The `PROVIDER = _C211Alberta(...)` line is intentionally awkward in the skeleton — a production version would read the enabled provinces from config and register a list of providers, which the loader supports (see "Loader extension" below).

## Loader extension for multi-instance providers

`load_builtin_providers` above assumes one `PROVIDER` per file. A file that wants to register several (one c211 instance per province) can export a `PROVIDERS` list instead:

```python
# in providers/registry.py, inside load_builtin_providers:
providers = getattr(mod, "PROVIDERS", None)
if providers is not None:
    for p in providers:
        registry.register(p)
    continue
provider = getattr(mod, "PROVIDER", None)
if provider is None:
    continue
if getattr(provider, "regions", None) is None:
    registry.register_default(provider)
else:
    registry.register(provider)
```

## Session changes

Two new columns on `InterviewSession`, and one identifier-format change:

```python
# models.py, InterviewSession
origin_country: Mapped[str | None] = mapped_column(String(100))
origin_region: Mapped[str | None] = mapped_column(String(100))
route_provider_id: Mapped[str | None] = mapped_column(String(50))
```

`nearby_service_ids` keeps its `list[str]` shape, but the strings become `"<provider_id>:<external_id>"`. For local, `"local:<uuid>"`. This is the one behavioural change to the existing chat flow — anything that assumed bare UUIDs in that list must now split on `:`.

## Integration points

**`set_location`**: replace the direct `_nearby_services` call with the registry. The Photon response's `properties` goes into `region_chain()`, `get_registry().resolve(chain)` returns a provider, `provider.search(...)` populates the index, `provider.id` is written to `route_provider_id`. The session's `origin_country` and `origin_region` come from the same Photon response.

**`_execute_get_service_details`**: parse the identifier as `<provider_id>:<external_id>`, look up the provider by id, call `detail_with_cache(provider, external_id)`, catch `ProviderNotFound` for the closure note and `ProviderTransient` for the lookup-failed note. The renderer needs the provider's `label`, `icon`, `attribution_text` — pass them through to the card payload so the badge displays without a lookup.

**`_render_service_full`**: the source badge in the chat card gets the provider's `label`/`icon` from the same place. For local, those are `"local"` and `"📍"`, already what the current UI renders.

**Startup**: `load_builtin_providers()` runs once in `create_app`, before `init_engine`. Any `RegistryError` aborts startup — a route that references an unregistered provider is a fail-fast condition, not a runtime one.

## Testing

Three test cases cover the routing:

1. **Edmonton address** → chain `["alberta", "canada"]` → `c211-ab` (if registered for Alberta) or `c211` (if only Canada is registered).
2. **Lloydminster T9V** → chain `["alberta", "canada"]` → `c211-ab`. **Lloydminster S9V** → chain `["saskatchewan", "canada"]` → `c211-sk`. This is the whole point of using the address, not the city name.
3. **US address with no US provider registered** → chain `["maine", "united states of america"]` → no match → `default` (local, or NDP if configured). The card badge shows the default's label so the operator sees "the source is local".

## What this leaves out, on purpose

- **Cross-provider dedup.** Concatenation only. Two rows for the same food bank from two sources are two rows.
- **Circuit breakers.** Connectors rely on `ProviderTransient` and the caller's error handling; a proper circuit breaker is a v2 concern.
- **Per-provider TTLs beyond a single `default_ttl_hours`.** The file mtime carries the entry's age; the cron uses a single configurable TTL. Per-provider TTLs are one dict away when they matter.
- **The actual c211/NDP request shapes.** Those need the real API, and the normalization layer is deliberately isolated to one method per provider so it is a small file to fill in once the response is in hand.

The plugin system is now a stable surface: the interface is set, the dispatch is settled, the cache is out of the critical path, and the session's identifier format carries enough information for `get_service_details` to route a stale index entry back to the provider that produced it. The remaining work is filling in one connector, which is where the real 211 API details belong.