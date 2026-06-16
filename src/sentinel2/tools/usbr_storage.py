#!/usr/bin/env python3
"""Fetch USBR reservoir storage (acre-feet) or elevation (ft) for a Bureau-of-
Reclamation reservoir USGS doesn't gauge — Lake Powell (Upper Colorado
hydrodata) or Lake Mead (RISE API).

Usage:
    python tools/usbr_storage.py --reservoir "Lake Mead" \\
        --from 2003-01-01 --to 2024-12-31 [--metric storage|elevation] [--use-mock]

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
    p.add_argument("--reservoir", required=True, help="name containing 'powell' or 'mead'")
    p.add_argument("--from", dest="date_from", required=True)
    p.add_argument("--to", dest="date_to", required=True)
    p.add_argument("--metric", default="storage", choices=["storage", "elevation"])
    p.add_argument("--force", action="store_true")
    p.add_argument("--use-mock", action="store_true", help="offline deterministic mode")
    p.add_argument("--log-level", default="INFO")
    a = p.parse_args()
    logging.basicConfig(level=a.log_level, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(message)s")
    r = level.fetch_usbr_reservoir(a.reservoir, a.date_from, a.date_to,
                                   metric=a.metric, force=a.force, use_mock=a.use_mock)
    logging.info("%s: %d points %s..%s %s", r["site_name"], r["point_count"],
                 r["min"], r["max"], r["unit"])
    json.dump({k: r[k] for k in
               ("site_id", "site_name", "unit", "point_count", "min", "max", "relative_path")},
              sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
