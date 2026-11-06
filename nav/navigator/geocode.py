"""Shared Photon helpers for /api/geocode* and set_location.

Builds a one-line display label from Photon's flat `properties` dict.
Photon returns structured fields — name, street, housenumber, city,
postcode, state, country — not a pre-joined `display_name`. We assemble
them in address order.

The old `short_display()` helper targeted Nominatim's kitchen-sink
addresses (state, county, region, country, postcodes duplicated in
display_name). Photon's results are already local and short enough to
show in full, and the heuristic hid street numbers on POI results: a
search for Union Gospel Mission yielded "Union Gospel Mission, Vancouver",
losing "601 East Hastings Street". Removed.
"""
from __future__ import annotations


def photon_display_name(props: dict | None) -> str:
    """Assemble a one-line label from Photon's flat `properties` dict.

    Order: name, street+housenumber, city, postcode, state, country.
    Empty parts and consecutive duplicates are dropped. Returns "" if
    `props` has nothing usable; callers decide on the fallback.
    """
    if not props:
        return ""
    hn = props.get("housenumber")
    street = props.get("street")
    street_full = (
        f"{hn} {street}".strip() if (hn and street)
        else (street or "")
    )

    parts = [
        props.get("name"),
        street_full,
        props.get("city"),
        props.get("postcode"),
        props.get("state"),
        props.get("country"),
    ]
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        s = str(p).strip()
        if not s:
            continue
        if out and out[-1].lower() == s.lower():
            continue
        out.append(s)
    return ", ".join(out)