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