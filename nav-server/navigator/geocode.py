"""Shared Nominatim helpers used by /api/geocode* and set_location."""
from __future__ import annotations

_ROAD_KEYS = ("road", "pedestrian", "footway", "path", "cycleway", "street")
_CITY_KEYS = ("city", "town", "village", "municipality", "suburb")


def short_display(addr: dict | None, fallback: str, *, query: str | None = None) -> str:
    """Build 'number street, city, postcode' from a Nominatim address object.

    Skips state / county / region / country so the label stays local and
    compact — a caseworker only cares about house-level identifiers.

    Nominatim sometimes omits `road` / `postcode` when the top hit is a
    place, street, or POI rather than a house. In that case we recover them
    from `fallback` (the full `display_name`) and `query` so the label
    stays useful rather than collapsing to `"123, Toronto"`.
    """
    if not addr:
        return fallback[:100]

    num = (addr.get("house_number") or "").strip()
    road = next(
        (str(addr[k]).strip() for k in _ROAD_KEYS if addr.get(k)),
        "",
    )
    city = next(
        (str(addr[k]).strip() for k in _CITY_KEYS if addr.get(k)),
        "",
    )
    postcode = (addr.get("postcode") or "").strip()

    # Recover `road` from display_name. Nominatim's display_name is
    # comma-joined starting at house level, so skip pure-number and
    # city/postcode segments and take the first remaining one.
    if not road and fallback:
        for seg in (s.strip() for s in fallback.split(",")):
            if not seg:
                continue
            if seg.isdigit():
                continue
            if city and city.lower() in seg.lower():
                continue
            if postcode and postcode.lower() in seg.lower():
                continue
            road = seg
            break

    # Recover `postcode` from the free-text query if the address dict
    # didn't carry one (common for place / highway results).
    if not postcode and query:
        for tok in query.replace(",", " ").split():
            t = tok.strip().upper()
            if (
                4 <= len(t) <= 10
                and any(c.isdigit() for c in t)
                and any(c.isalpha() for c in t)
            ):
                postcode = tok.strip()
                break

    street = f"{num} {road}".strip()
    if not street:
        # Last resort for POI hits with no road at all.
        street = (addr.get("amenity") or addr.get("place") or "").strip()

    parts = [p for p in (street, city, postcode) if p]
    return ", ".join(parts) if parts else fallback[:100]