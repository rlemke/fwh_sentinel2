"""Resolve a place name to an AOI bbox via the OpenStreetMap Nominatim geocoder.

``resolve("Apuí, Amazonas, Brazil")`` -> a ``min_lon,min_lat,max_lon,max_lat``
string the rest of the pipeline consumes. Two modes:

- ``buffer_km > 0`` (default): a box of half-size ``buffer_km`` centered on the
  place's point. Practical — a municipality's full polygon can be enormous
  (Apuí is ~54,000 km²), which would fan out into hundreds of Sentinel-2 scenes.
- ``buffer_km == 0``: the geocoder's own bounding box (use for small places).

Nominatim is free and keyless but rate-limited (≈1 req/s) and requires a
descriptive User-Agent — fine for one lookup per run. The mock path is offline
and deterministic.
"""

from __future__ import annotations

import math
from typing import Any

_USER_AGENT = "facetwork-sentinel2-landchange (research example)"


def _box_around(lat: float, lon: float, buffer_km: float) -> tuple[float, float, float, float]:
    dlat = buffer_km / 111.32
    dlon = buffer_km / (111.32 * max(math.cos(math.radians(lat)), 1e-6))
    return (round(lon - dlon, 5), round(lat - dlat, 5), round(lon + dlon, 5), round(lat + dlat, 5))


def resolve(
    place: str,
    *,
    buffer_km: float = 10.0,
    nominatim_url: str = "https://nominatim.openstreetmap.org",
    use_mock: bool = False,
) -> dict[str, Any]:
    """Return {aoi, lat, lon, display_name, used_mock} for ``place``."""
    if not place or not place.strip():
        raise ValueError("place must be a non-empty name")
    if use_mock:
        return _resolve_mock(place, buffer_km)
    return _resolve_real(place, buffer_km, nominatim_url)


def _resolve_real(place: str, buffer_km: float, nominatim_url: str) -> dict[str, Any]:
    import requests

    resp = requests.get(
        nominatim_url.rstrip("/") + "/search",
        params={"q": place, "format": "json", "limit": 1},
        headers={"User-Agent": _USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        raise LookupError(f"no geocoding match for place {place!r}")
    h = hits[0]
    lat, lon = float(h["lat"]), float(h["lon"])
    if buffer_km > 0:
        w, s, e, n = _box_around(lat, lon, buffer_km)
    else:
        # Nominatim boundingbox is [south, north, west, east].
        bb = [float(x) for x in h["boundingbox"]]
        s, n, w, e = bb[0], bb[1], bb[2], bb[3]
    aoi = f"{round(w, 5)},{round(s, 5)},{round(e, 5)},{round(n, 5)}"
    return {"aoi": aoi, "lat": lat, "lon": lon,
            "display_name": h.get("display_name", place), "used_mock": False}


def _resolve_mock(place: str, buffer_km: float) -> dict[str, Any]:
    """Deterministic offline geocode: a stable point derived from the name."""
    import hashlib

    seed = int(hashlib.sha256(place.encode()).hexdigest()[:8], 16)
    lat = -10.0 + (seed % 2000) / 100.0 - 10.0   # roughly within Amazon latitudes
    lon = -70.0 + (seed // 2000 % 3000) / 100.0   # roughly within Amazon longitudes
    w, s, e, n = _box_around(lat, lon, buffer_km or 10.0)
    return {"aoi": f"{w},{s},{e},{n}", "lat": round(lat, 5), "lon": round(lon, 5),
            "display_name": f"{place} (mock)", "used_mock": True}
