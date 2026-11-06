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