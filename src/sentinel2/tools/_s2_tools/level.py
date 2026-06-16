"""Lake-surface elevation (water *level*) from the USGS NWIS Daily Values service.

The gauge counterpart to NDWI water *extent*: a satellite sees the water's
footprint (km²); a gauge measures the surface *height* (ft/m). They track for a
lake, but non-linearly — the Great Salt Lake is a flat pan, so a ~6 ft level
drop bares hundreds of km². Overlaying the two makes that hypsometry visible.

Source: ``waterservices.usgs.gov/nwis/dv`` — free, no auth, daily, back to the
1960s. **US gauges only.** Default site = Great Salt Lake at Saltair Boat Harbor
(south arm), parameter 62614 = "lake/reservoir water surface elevation above
NGVD 1929, ft". Series are cached (sidecar) like every other artifact; the mock
path is offline.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Any

from _s2_tools import s2_mocks, sidecar, storage

LAKE_LEVEL = "lake-level"

_NWIS = "https://waterservices.usgs.gov/nwis/dv/"
_NWIS_SITE = "https://waterservices.usgs.gov/nwis/site/"
_USER_AGENT = "facetwork-sentinel2-landchange"

# Great Salt Lake at Saltair Boat Harbor (south arm); 62614 = elevation, ft NGVD29.
GREAT_SALT_LAKE = "10010000"
ELEV_PARAM = "62614"

# Lake/reservoir water-level parameter codes, in preference order:
# 62614 = elevation above NGVD29 (ft); 62615 = above NAVD88 (ft); 00062 = elevation,
# datum varies (ft); 00065 = gage height (ft) — a *relative* stage in a local datum
# (e.g. Clear Lake, CA's "Rumsey" zero), used last and only with siteType=LK so it
# catches lake-stage gauges (not river stations). Any one gives a self-consistent
# level series for one site; the true-elevation datums win when a lake has both.
ELEV_PARAMS = ("62614", "62615", "00062", "00065")

# Generic tokens dropped before name-matching a place against a station name, so
# "Lake Powell" matches "LAKE POWELL AT GLEN CANYON DAM" on the rare token.
_NAME_STOP = {
    "lake", "lakes", "reservoir", "res", "pond", "the", "of", "at", "near", "nr",
    "creek", "ck", "c", "river", "r", "dam", "pool", "fork", "bay", "harbor", "boat",
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "id", "il", "in",
    "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne",
    "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "usa", "us",
}


def _rel(site_id: str, date_from: str, date_to: str, param: str) -> str:
    return f"{site_id}/{param}/{date_from}_{date_to}.json"


def decimal_year(date_str: str) -> float:
    """'YYYY-MM-DD' -> fractional year (so daily levels and per-year extent share
    one linear x axis without a Chart.js time adapter)."""
    y = int(date_str[:4])
    doy = (date(y, int(date_str[5:7]), int(date_str[8:10])) - date(y, 1, 1)).days
    return round(y + doy / 365.0, 4)


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and t not in _NAME_STOP}


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_rdb(text: str) -> list[dict[str, str]]:
    """Parse USGS RDB (tab-delimited; '#' comments, a header row, then a format
    row, then data) into a list of column→value dicts."""
    rows = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    if len(rows) < 2:
        return []
    header = rows[0].split("\t")
    out = []
    for ln in rows[2:]:  # rows[1] is the format spec line (5s, 15s, …)
        cells = ln.split("\t")
        if len(cells) == len(header):
            out.append(dict(zip(header, cells)))
    return out


def _discover_gauges(west, south, east, north) -> list[dict[str, Any]]:
    """USGS lake/reservoir (siteType=LK) elevation gauges with daily values in the
    bbox, tagged with the (priority-order) elevation param they report."""
    import requests

    seen: dict[str, dict[str, Any]] = {}
    for param in ELEV_PARAMS:
        try:
            resp = requests.get(
                _NWIS_SITE,
                params={"format": "rdb",
                        "bBox": f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}",
                        "parameterCd": param, "siteType": "LK",
                        "hasDataTypeCd": "dv", "siteStatus": "all"},
                headers={"User-Agent": _USER_AGENT}, timeout=60)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue  # 404 = no sites for this param/bbox
        for row in _parse_rdb(resp.text):
            sid = row.get("site_no")
            if not sid or sid in seen:  # first (highest-priority) param wins
                continue
            try:
                lat, lon = float(row["dec_lat_va"]), float(row["dec_long_va"])
            except (KeyError, ValueError):
                continue
            seen[sid] = {"site_id": sid, "site_name": row.get("station_nm", ""),
                         "lat": lat, "lon": lon, "param": param}
    return list(seen.values())


def find_lake_gauge(
    aoi: str, *, place: str = "", site_id: str = "", margin_deg: float = 0.1,
    use_mock: bool = False,
) -> dict[str, Any]:
    """Resolve the best USGS lake-elevation gauge for an AOI. An explicit
    ``site_id`` is returned as-is (override). Otherwise discover LK gauges in the
    margin-expanded AOI bbox and pick the one whose station name best matches
    ``place`` (then nearest to the AOI centroid). Raises if none are found —
    many lakes (e.g. Bureau-of-Reclamation reservoirs like Lake Mead) have no
    USGS elevation gauge. Returns {site_id, param, site_name, lat, lon,
    distance_km, confident, candidate_count, source}."""
    if site_id:
        return {"site_id": site_id, "param": ELEV_PARAM, "site_name": "",
                "lat": 0.0, "lon": 0.0, "distance_km": 0.0, "confident": True,
                "candidate_count": 1, "source": "explicit"}
    if use_mock:
        return {"site_id": GREAT_SALT_LAKE, "param": ELEV_PARAM,
                "site_name": f"MOCK LAKE {GREAT_SALT_LAKE}", "lat": 40.7313,
                "lon": -112.2136, "distance_km": 0.0, "confident": True,
                "candidate_count": 1, "source": "mock"}

    w, s, e, n = (float(x) for x in aoi.split(","))
    cx, cy = (w + e) / 2, (s + n) / 2
    cands = _discover_gauges(w - margin_deg, s - margin_deg, e + margin_deg, n + margin_deg)
    if not cands:
        raise ValueError(
            f"no USGS lake-elevation gauge (siteType=LK, param "
            f"{'/'.join(ELEV_PARAMS)}) within {margin_deg}° of aoi={aoi}. This lake "
            f"may not be USGS-gauged (e.g. Reclamation reservoirs like Lake Mead) — "
            f"pass an explicit site_id, or omit the level overlay.")

    place_tokens = _tokens(place)
    for c in cands:
        c["distance_km"] = round(_haversine_km(cy, cx, c["lat"], c["lon"]), 1)
        c["name_match"] = len(place_tokens & _tokens(c["site_name"]))
    best = sorted(cands, key=lambda c: (-c["name_match"], c["distance_km"]))[0]
    # Confident if the place name matched a station token, else only if it's close.
    confident = bool(best["name_match"]) if place_tokens else best["distance_km"] < 25.0
    return {"site_id": best["site_id"], "param": best["param"],
            "site_name": best["site_name"], "lat": round(best["lat"], 5),
            "lon": round(best["lon"], 5), "distance_km": best["distance_km"],
            "confident": confident, "candidate_count": len(cands),
            "source": "usgs-nwis-site"}


def fetch_lake_level(
    site_id: str, date_from: str, date_to: str, *,
    param: str = ELEV_PARAM, force: bool = False, use_mock: bool = False,
) -> dict[str, Any]:
    """Daily lake elevation for a USGS site over [date_from, date_to]. Caches the
    series; returns {site_id, site_name, unit, series:[{date,value}], point_count,
    min, max, relative_path, was_cached}."""
    rel = _rel(site_id, date_from, date_to, param)
    if not force and sidecar.exists(LAKE_LEVEL, rel):
        doc = json.loads(storage.read_text(sidecar.cache_path(LAKE_LEVEL, rel)))
        return {**doc, "relative_path": rel, "was_cached": True}

    if use_mock:
        doc = s2_mocks.mock_lake_level(site_id, date_from, date_to)
        source = f"mock://{site_id}/{param}"
    else:
        doc = _fetch_real(site_id, date_from, date_to, param)
        source = f"{_NWIS}?sites={site_id}&parameterCd={param}"

    sidecar.write(LAKE_LEVEL, rel, json.dumps(doc).encode("utf-8"),
                  source=source, tool="fetch_lake_level")
    return {**doc, "relative_path": rel, "was_cached": False}


def load_series(relative_path: str) -> dict[str, Any]:
    """Load a cached level series by its relative_path (used by the renderer)."""
    return json.loads(storage.read_text(sidecar.cache_path(LAKE_LEVEL, relative_path)))


def _fetch_real(site_id, date_from, date_to, param) -> dict[str, Any]:
    import requests

    # Try the requested param first, then the other elevation params — an
    # auto-discovered site may report a different datum than the default.
    params_to_try = [param] + [p for p in ELEV_PARAMS if p != param]
    ts: list = []
    for pc in params_to_try:
        resp = requests.get(
            _NWIS,
            params={"format": "json", "sites": site_id, "parameterCd": pc,
                    "startDT": date_from, "endDT": date_to},
            headers={"User-Agent": _USER_AGENT}, timeout=60,
        )
        resp.raise_for_status()
        ts = resp.json().get("value", {}).get("timeSeries", [])
        if ts and ts[0].get("values", [{}])[0].get("value"):
            break
    if not ts:
        raise ValueError(f"USGS NWIS returned no elevation series for site {site_id} "
                         f"(params {'/'.join(params_to_try)}) over {date_from}..{date_to}")
    s = ts[0]
    name = s["sourceInfo"]["siteName"]
    unit = s["variable"]["unit"]["unitCode"]  # e.g. "ft"
    series = [
        {"date": v["dateTime"][:10], "value": float(v["value"])}
        for v in s["values"][0]["value"]
        if v.get("value") not in ("", None, "-999999")
    ]
    vals = [p["value"] for p in series]
    return {"site_id": site_id, "site_name": name, "unit": unit, "series": series,
            "point_count": len(series),
            "min": round(min(vals), 2) if vals else None,
            "max": round(max(vals), 2) if vals else None}
