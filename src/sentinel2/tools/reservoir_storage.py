#!/usr/bin/env python3
"""Fetch a USGS reservoir storage series (param 00054, acre-feet) for a site —
the actual *quantity* of water over time, not just its surface height.

Usage:
    python tools/reservoir_storage.py --site-id 06857050 \\
        --from 2003-01-01 --to 2024-12-31 [--use-mock]

Caches the daily series (sidecar) like every other artifact; the renderer
consumes it via the returned relative_path to overlay storage on water extent.
Reclamation reservoirs (Powell, Mead) don't report 00054 — use elevation
(lake_level.py) for those.

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
    p.add_argument("--site-id", required=True, help="USGS site id (must report 00054)")
    p.add_argument("--from", dest="date_from", required=True)
    p.add_argument("--to", dest="date_to", required=True)
    p.add_argument("--force", action="store_true", help="bypass the cache")
    p.add_argument("--use-mock", action="store_true", help="offline deterministic mode")
    p.add_argument("--log-level", default="INFO")
    a = p.parse_args()
    logging.basicConfig(level=a.log_level, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(message)s")
    r = level.fetch_lake_storage(a.site_id, a.date_from, a.date_to,
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
