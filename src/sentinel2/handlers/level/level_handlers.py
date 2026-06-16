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


_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.FetchLakeLevel": handle_fetch_lake_level,
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
