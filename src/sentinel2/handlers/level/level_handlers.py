"""Level handler — fetch a USGS lake-elevation series (water *level*).

Thin coercion over ``_s2_tools.level``; the cached series is consumed by the
``s2.timeseries.WaterTimeSeriesMap`` renderer (via ``level_relative_path``) to
overlay height against NDWI water extent.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..shared.s2_utils import level

logger = logging.getLogger("s2.level")
NAMESPACE = "s2.level"


def handle_resolve_lake_gauge(params: dict[str, Any]) -> dict[str, Any]:
    # Comma-separated param codes to search; "" = the default elevation set.
    pcsv = params.get("params", "")
    pset = tuple(p.strip() for p in pcsv.split(",") if p.strip()) or level.ELEV_PARAMS
    res = level.find_lake_gauge(
        aoi=params["aoi"],
        place=params.get("place", ""),
        site_id=params.get("site_id", ""),
        margin_deg=float(params.get("margin_deg", 0.1)),
        params=pset,
        use_mock=bool(params.get("use_mock", False)),
    )
    msg = ("ResolveLakeGauge aoi=%s place=%r -> %s %r param=%s (%.1f km, %d candidates)"
           % (params["aoi"], params.get("place", ""), res["site_id"],
              res["site_name"], res["param"], res["distance_km"], res["candidate_count"]))
    if res["confident"]:
        logger.info(msg)
    else:
        logger.warning("%s — LOW CONFIDENCE (no name match); verify or pass site_id", msg)
    return res


def handle_fetch_lake_level(params: dict[str, Any]) -> dict[str, Any]:
    res = level.fetch_lake_level(
        site_id=params.get("site_id", level.GREAT_SALT_LAKE),
        date_from=params["date_from"],
        date_to=params["date_to"],
        param=params.get("param", level.ELEV_PARAM),
        force=bool(params.get("force", False)),
        use_mock=bool(params.get("use_mock", False)),
    )
    logger.info("FetchLakeLevel site=%s %s..%s -> %d points (%s..%s %s)",
                res["site_id"], params["date_from"], params["date_to"],
                res["point_count"], res["min"], res["max"], res["unit"])
    # The full series stays in the cache; return a compact summary.
    return {k: res[k] for k in
            ("relative_path", "site_name", "unit", "point_count", "min", "max")}


def handle_fetch_reservoir_storage(params: dict[str, Any]) -> dict[str, Any]:
    res = level.fetch_lake_storage(
        site_id=params["site_id"],
        date_from=params["date_from"],
        date_to=params["date_to"],
        force=bool(params.get("force", False)),
        use_mock=bool(params.get("use_mock", False)),
    )
    logger.info("FetchReservoirStorage site=%s %s..%s -> %d points (%s..%s %s)",
                res["site_id"], params["date_from"], params["date_to"],
                res["point_count"], res["min"], res["max"], res["unit"])
    return {k: res[k] for k in
            ("relative_path", "site_name", "unit", "point_count", "min", "max")}


_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.ResolveLakeGauge": handle_resolve_lake_gauge,
    f"{NAMESPACE}.FetchLakeLevel": handle_fetch_lake_level,
    f"{NAMESPACE}.FetchReservoirStorage": handle_fetch_reservoir_storage,
}


def handle(payload: dict) -> dict:
    """RegistryRunner entrypoint."""
    return _DISPATCH[payload["_facet_name"]](payload)


def register_handlers(runner) -> None:
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
        )


def register_level_handlers(poller) -> None:
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
