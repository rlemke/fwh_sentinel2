"""Time-series handler — render the multi-year water viewer."""

from __future__ import annotations

import logging
import os
from typing import Any

from ..shared.s2_utils import timeseries

logger = logging.getLogger("s2.timeseries")
NAMESPACE = "s2.timeseries"


def handle_water_timeseries_map(params: dict[str, Any]) -> dict[str, Any]:
    return timeseries.render_water_timeseries(
        aoi=params["aoi"],
        index=params.get("index", "ndwi"),
        water_threshold=float(params.get("water_threshold", 0.1)),
        title=params.get("title", "Surface water over time"),
        basemap_url=params.get("basemap_url", ""),
    )


_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.WaterTimeSeriesMap": handle_water_timeseries_map,
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


def register_timeseries_handlers(poller) -> None:
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
