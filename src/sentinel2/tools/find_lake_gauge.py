#!/usr/bin/env python3
"""Resolve the best USGS lake-elevation gauge for an AOI (or place name).

Usage:
    python tools/find_lake_gauge.py --aoi MIN_LON,MIN_LAT,MAX_LON,MAX_LAT \\
        [--place "Lake Okeechobee, Florida"] [--site-id 10010000] [--use-mock]

Discovers lake/reservoir (siteType=LK) gauges reporting a water-level parameter
in the margin-expanded AOI and picks the best name match (else nearest). An
explicit --site-id is returned as-is.

stdout: JSON {site_id, param, site_name, lat, lon, distance_km, confident, ...}
stderr: log lines.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _s2_tools import level  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aoi", required=True, help="min_lon,min_lat,max_lon,max_lat")
    p.add_argument("--place", default="", help="place name, for name-matching the station")
    p.add_argument("--site-id", default="", help="explicit USGS site id (skips discovery)")
    p.add_argument("--margin-deg", type=float, default=0.1, help="bbox expansion for the search")
    p.add_argument("--use-mock", action="store_true", help="offline deterministic mode")
    p.add_argument("--log-level", default="INFO")
    a = p.parse_args()
    logging.basicConfig(level=a.log_level, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(message)s")
    g = level.find_lake_gauge(a.aoi, place=a.place, site_id=a.site_id,
                              margin_deg=a.margin_deg, use_mock=a.use_mock)
    logging.info("gauge %s %r param=%s (%.1f km, confident=%s)", g["site_id"],
                 g["site_name"], g["param"], g["distance_km"], g["confident"])
    json.dump(g, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
