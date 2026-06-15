"""Geo handler — resolve a place name to an AOI bbox (Nominatim / OSM)."""

from __future__ import annotations

import logging
import os
from typing import Any

from ..shared.s2_utils import geocode

logger = logging.getLogger("s2.geo")
NAMESPACE = "s2.geo"


def handle_resolve_aoi(params: dict[str, Any]) -> dict[str, Any]:
    res = geocode.resolve(
        place=params["place"],
        buffer_km=float(params.get("buffer_km", 10.0)),
        nominatim_url=params.get("nominatim_url", "https://nominatim.openstreetmap.org"),
        use_mock=bool(params.get("use_mock", False)),
    )
    logger.info("ResolveAOI %r -> aoi=%s (%s)", params["place"], res["aoi"], res["display_name"])
    return res


_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.ResolveAOI": handle_resolve_aoi,
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


def register_geo_handlers(poller) -> None:
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
