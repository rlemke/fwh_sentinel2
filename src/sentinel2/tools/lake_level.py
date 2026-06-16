#!/usr/bin/env python3
"""Fetch a USGS lake water-level (elevation or gage-height) series for a site.

Usage:
    python tools/lake_level.py --site-id 10010000 --from 2003-07-01 --to 2024-12-31 \\
        [--param 62614] [--use-mock]

Caches the daily series (sidecar) like every other artifact; the renderer
consumes it via the returned relative_path to overlay level on water extent.

stdout: JSON {site_id, site_name, unit, point_count, min, max, relative_path}
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
    p.add_argument("--site-id", default=level.GREAT_SALT_LAKE, help="USGS site id")
    p.add_argument("--from", dest="date_from", required=True)
    p.add_argument("--to", dest="date_to", required=True)
    p.add_argument("--param", default=level.ELEV_PARAM,
                   help="USGS parameter code (62614/62615/00062 elevation, 00065 gage height)")
    p.add_argument("--force", action="store_true", help="bypass the cache")
    p.add_argument("--use-mock", action="store_true", help="offline deterministic mode")
    p.add_argument("--log-level", default="INFO")
    a = p.parse_args()
    logging.basicConfig(level=a.log_level, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(message)s")
    r = level.fetch_lake_level(a.site_id, a.date_from, a.date_to, param=a.param,
                               force=a.force, use_mock=a.use_mock)
    logging.info("%s: %d points %s..%s %s (%s)", r["site_id"], r["point_count"],
                 r["min"], r["max"], r["unit"], r["site_name"])
    json.dump({k: r[k] for k in
               ("site_id", "site_name", "unit", "point_count", "min", "max", "relative_path")},
              sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
