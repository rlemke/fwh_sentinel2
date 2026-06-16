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
from datetime import date
from typing import Any

from _s2_tools import s2_mocks, sidecar, storage

LAKE_LEVEL = "lake-level"

_NWIS = "https://waterservices.usgs.gov/nwis/dv/"
_USER_AGENT = "facetwork-sentinel2-landchange"

# Great Salt Lake at Saltair Boat Harbor (south arm); 62614 = elevation, ft NGVD29.
GREAT_SALT_LAKE = "10010000"
ELEV_PARAM = "62614"


def _rel(site_id: str, date_from: str, date_to: str, param: str) -> str:
    return f"{site_id}/{param}/{date_from}_{date_to}.json"


def decimal_year(date_str: str) -> float:
    """'YYYY-MM-DD' -> fractional year (so daily levels and per-year extent share
    one linear x axis without a Chart.js time adapter)."""
    y = int(date_str[:4])
    doy = (date(y, int(date_str[5:7]), int(date_str[8:10])) - date(y, 1, 1)).days
    return round(y + doy / 365.0, 4)


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

    resp = requests.get(
        _NWIS,
        params={"format": "json", "sites": site_id, "parameterCd": param,
                "startDT": date_from, "endDT": date_to},
        headers={"User-Agent": _USER_AGENT}, timeout=60,
    )
    resp.raise_for_status()
    ts = resp.json().get("value", {}).get("timeSeries", [])
    if not ts:
        raise ValueError(f"USGS NWIS returned no series for site {site_id} param {param} "
                         f"over {date_from}..{date_to}")
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
