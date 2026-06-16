"""Deterministic offline fixtures for ``use_mock=True``.

No network, no GDAL/rasterio. Scenes and per-scene index grids are derived
deterministically from the AOI + date window + scene id, so a mock run computes
a real (if synthetic) composite/change and is reproducible in tests. Real
imagery flows through the same function signatures in ``stac`` / ``raster``.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

# Small synthetic raster size for the mock (keeps fixtures tiny).
MOCK_W = 16
MOCK_H = 16


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def mock_scene_ids(aoi: str, date_from: str, date_to: str, max_cloud: float) -> list[str]:
    """A stable handful of scene ids for the window (3-6 scenes)."""
    n = 3 + (_seed(aoi, date_from, date_to) % 4)
    return [f"S2_MOCK_{date_from}_{date_to}_{i:02d}" for i in range(n)]


def _year_of(scene_id: str) -> int:
    """Pull the acquisition year from a mock scene id (``S2_MOCK_2024-...``)."""
    for tok in scene_id.replace("_", "-").split("-"):
        if len(tok) == 4 and tok.isdigit():
            return int(tok)
    return 2020


def mock_index_grid(scene_id: str, aoi: str, index: str) -> list[list[float]]:
    """A deterministic WxH grid of index values in [-1, 1].

    Models a realistic scene rather than pure noise so the change methods have
    something to find: a smooth spatial gradient (greener toward the top-right)
    that is *shared across epochs*, plus a localized **vegetation loss** in the
    lower-left quadrant for recent (>= 2022) scenes — e.g. a clear-cut / new
    development. Plus a little per-scene noise that the epoch median smooths out.
    """
    year = _year_of(scene_id)
    grid: list[list[float]] = []
    for y in range(MOCK_H):
        row = []
        for x in range(MOCK_W):
            spatial = (x / (MOCK_W - 1)) * 0.5 + ((MOCK_H - 1 - y) / (MOCK_H - 1)) * 0.5
            v = -0.2 + 1.2 * spatial  # baseline NDVI ~ [-0.2, 1.0]
            if year >= 2022 and x < MOCK_W / 2 and y > MOCK_H / 2:
                v -= 0.45  # recent vegetation loss in the lower-left
            noise = ((_seed(scene_id, index, str(x), str(y)) % 21) - 10) / 100.0  # ±0.10
            row.append(round(max(-1.0, min(1.0, v + noise)), 4))
        grid.append(row)
    return grid


def mock_lake_level(site_id: str, date_from: str, date_to: str) -> dict:
    """A deterministic weekly elevation series in plausible Great-Salt-Lake range
    (~4188–4196 ft): a slow decline to a mid-window trough (mirroring the 2022
    record low) and a partial recovery, plus tiny per-week jitter. Offline."""
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    span = max((end - start).days, 1)
    series = []
    d = start
    while d <= end:
        t = (d - start).days / span  # 0..1
        # V-shape: 4196 -> ~4189 trough at t=0.85 -> small rebound.
        trough = 0.85
        if t <= trough:
            elev = 4196.0 - 7.0 * (t / trough)
        else:
            elev = 4189.0 + 5.0 * ((t - trough) / (1 - trough))
        jitter = ((_seed(site_id, d.isoformat()) % 11) - 5) / 100.0  # ±0.05
        series.append({"date": d.isoformat(), "value": round(elev + jitter, 2)})
        d += timedelta(days=7)
    vals = [p["value"] for p in series]
    return {"site_id": site_id, "site_name": f"MOCK LAKE {site_id}", "unit": "ft",
            "series": series, "point_count": len(series),
            "min": round(min(vals), 2), "max": round(max(vals), 2)}
