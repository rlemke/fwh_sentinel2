# sentinel2-landchange tools

CLI surface over `_s2_tools/` — the same functions the FFL handlers call, so the
terminal and the runtime share one cache (`$AFL_CACHE_ROOT/s2/`) and one code path.

```
search_scenes.py   STAC search → {count, scene_ids}              [shipped]
find_lake_gauge.py AOI/place → best USGS lake gauge               [shipped]
lake_level.py      USGS site → cached daily level series          [shipped]
reservoir_storage USGS site → cached daily storage (acre-feet)    [shipped]
fetch_scene_index  one scene → cached AOI-clipped index raster   [TODO CLI; handler + lib done]
composite          epoch median composite over cached scenes     [TODO CLI; handler + lib done]
detect_change      baseline vs recent → change raster + stats     [TODO CLI; handler + lib done]
render_change_map  change raster → MapLibre HTML + tiles          [TODO CLI; handler + lib done]
```

The water-*level* pair (`find_lake_gauge` + `lake_level`) backs the
`WaterLevelTimeSeries` workflow: discover a lake's USGS gauge by name, then pull
its daily elevation / gage-height to overlay on satellite water *extent*. Worked
lake studies (Great Salt Lake / Okeechobee / Clear Lake) are in
[`EXAMPLES.md`](../../../EXAMPLES.md).

Each CLI is one `<name>.py` (argparse, stdout=JSON, stderr=logs, `main() -> int`)
plus a thin `<name>.sh` wrapper, per `agent-spec/tools-pattern.agent-spec.yaml`.
`search_scenes` is the shipped reference; the TODO rows wrap the corresponding
`_s2_tools` function the same way (the library and FFL handlers already exist —
only the CLI shell is pending).

Examples (offline / live):

```bash
# note: use --aoi=... (leading-minus bbox would otherwise look like a flag)
python tools/search_scenes.py --aoi=-122.55,37.70,-122.35,37.85 \
  --from 2024-06-01 --to 2024-09-30 --use-mock

# which USGS gauge measures this lake? (live)
python tools/find_lake_gauge.py --aoi=-122.916,38.934,-122.635,39.129 \
  --place "Clear Lake, California"            # -> 11450000 CLEAR LK A LAKEPORT

# pull that lake's daily level series (live, cached)
python tools/lake_level.py --site-id 11450000 --from 2003-07-01 --to 2024-12-31 --param 00065
```

`--use-mock` runs against deterministic fixtures (`_s2_tools/s2_mocks.py`) — no
network, no GDAL. Drop it to hit the real path (real STAC search + COG read are
implemented in `_s2_tools/stac.py` and `_s2_tools/raster.py`); that needs
`pip install rio-tiler requests`.
