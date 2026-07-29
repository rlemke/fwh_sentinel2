# Water time-series viewer

**Namespace:** `s2.timeseries` ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (namespace `s2.timeseries`) ·
**Handlers:** `src/sentinel2/handlers/timeseries/timeseries_handlers.py` ·
**Tools:** `src/sentinel2/tools/_s2_tools/timeseries.py` ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_water_timeseries`, `test_lake_level_mock_and_overlay`, `test_reservoir_storage_mock`, `test_timeseries_window_selection`)

## Overview

`s2.timeseries.WaterTimeSeriesMap` renders the multi-year surface-water viewer: it
discovers the per-year NDWI (or MNDWI) composites the [fan-out](fan-out.md)'s
`ScanYears` left in cache, turns each year's water mask into a tile layer, and emits
one MapLibre HTML with a **year slider / tab bar** plus a Chart.js water-area (km²)
line chart — so you scrub the years and watch a lake shrink and recover. Optionally
it overlays a **gauge series** (level or storage, from [gauges](gauges.md)) on a
second chart axis, putting satellite *footprint* and gauge *height/quantity* on one
timeline.

## How it works

`timeseries.render_water_timeseries()`:

1. **Discover composites** — lists `composite/<aoi_key>/<index>/` cache entries, keeps
   one per year (`fn[:4]` = year). When `months_from`/`months_to` are given it
   accepts only that window's file per year (`<yr>-<mf>_<yr>-<mt>.npz`), so a
   dry-season run never silently renders a stale summer composite
   (`test_timeseries_window_selection`). Raises `FileNotFoundError` "run ScanYears"
   if none found.
2. **Per year** — loads the composite, builds the water mask (`arr > water_threshold`),
   computes water area in km² (`_area_km2`, a cos-latitude pixel-area estimate), and
   (if the geo stack is present) writes a per-year XYZ tile pyramid `tiles/<year>/…`
   in blue (`_WATER_RGB`) reusing `map_render._zoom_range` / a `morecantile` TMS.
3. **Optional level overlay** — the handler loads a cached gauge series
   (`level.load_series(level_relative_path)`); `_level_cfg` projects the daily series
   and the per-year extent onto a shared fractional-year x axis (`level.decimal_year`)
   and thins the line to ≤600 embedded points.
4. **HTML** — `_html`/`_TS_HTML`: a MapLibre map with one raster layer per year
   (visibility toggled by the active tab), a slider + tab bar, and a Chart.js chart —
   single-axis (extent only) or **dual-axis** (extent km² right, level/storage left)
   when a `level` series is supplied.

## Fan-out

**Single-task — no fan-out.** It is a reduce/render over the per-year composites the
`ScanYears` fan-out already produced, ordered behind it with `after`.
The per-year parallelism lives in [fan-out](fan-out.md).

## Data & fields

- **Discovery key:** `composite/<aoi_key>/<index>/<YYYY>-<mf>_<YYYY>-<mt>.npz`; the
  year is the filename's first 4 chars.
- **Water mask:** `index > water_threshold`; `series[i]` = `{year, area_km2}`.
- **Level cfg fields:** `unit` (`ft` / `ac-ft`), `line` (`[decimal_year, value]`),
  `extentPoints` (`[year+0.54, area_km2]` — mid-window so points align in x),
  `min`/`max`, `siteName`. The chart's left-axis label switches to "storage" when
  the unit contains `ac` (else "level").
- **`WaterTimeSeriesMap` returns:** `aoi_key`, `output_dir`, `html_path`,
  `year_count` (the tool also returns `has_level`, asserted in tests).
- No attribute filtering — the "filter" is the water threshold over the index.

## External libraries / binaries

- **`rio-tiler`** (pip, `[geo]`; pulls `rasterio` + `morecantile`) — **optional**;
  per-year tile pyramids. Without it the chart + slider still render (a `geo=false`
  config), just no map raster layers.
- **`numpy`** (core dep) — mask + RGB array construction.
- **MapLibre GL JS 4.7.1** and **Chart.js 4.4.1** — browser CDN dependencies of the
  emitted HTML (unpkg / jsDelivr), not Python deps.

## Facets & workflows

| Facet | Kind | Effect / Cost | Purpose |
|---|---|---|---|
| `WaterTimeSeriesMap(aoi, index="ndwi", water_threshold=0.1, title="Surface water over time", basemap_url="", months_from="", months_to="", level_relative_path="") => (aoi_key, output_dir, html_path, year_count)` | event | io / cheap | Render the per-year water-extent viewer (+ optional gauge overlay) |

`Effect(kind="io")`, `Cost(tier="cheap")`. Callers order it `after ScanYears` —
naming a `foreach` step waits for every iteration. It is the render leaf of the `WaterTimeSeries` /
`WaterLevelTimeSeries` / `WaterStorageTimeSeries` / `ReservoirStorageUSBR` workflows
(see [workflows](workflows.md)).

## Cache / output

- **Output bundle** at `output/s2-timeseries/<aoi_key>/`: `index.html` +
  `tiles/<year>/{z}/{x}/{y}.png` per year. Output, not cache (no sidecar).
- Reads the `composite` cache (via [change-detection](change-detection.md)'s
  `Composite`) and the `lake-level` cache (via [gauges](gauges.md)). Local or
  S3/MinIO per `FW_STORAGE`.

## Gotchas & notes

- **Window selection prevents stale renders** — passing `months_from`/`months_to`
  is how you disambiguate two seasonal windows cached for the same year+AOI; without
  them the most recent window per year is used.
- **The gauge overlay is loaded here but fetched elsewhere** — the network fetch is
  its own (external) [gauges](gauges.md) step; this renderer only reads the cached
  series (an `io` effect), keeping the render pure-ish.
- **Extent vs level track non-linearly** — a flat lake bares huge area for a small
  height drop; the dual-axis chart makes that hypsometry visible, but don't expect a
  monotone area↔height map (a point gauge vs a multi-arm AOI). See the README's Great
  Salt Lake / Okeechobee write-ups and `EXAMPLES.md`.
- **Optical-water ceiling** — the water mask maps *open* water, not emergent marsh;
  even tuned (fitted bbox + higher `FW_S2_MAX_SIZE` + dry-season MNDWI) a marshy lake
  like Okeechobee is a lower bound on the true footprint (README "Ceiling (honest)").

## Related specs

- [fan-out](fan-out.md) — `ScanYears` produces the per-year composites this discovers.
- [change-detection](change-detection.md) — the `Composite` that writes those per-year rasters.
- [gauges](gauges.md) — the level/storage series overlaid on the chart.
- [change-map](change-map.md) — the sibling single-epoch renderer (shared basemap/zoom helpers).
- [workflows](workflows.md) — the water time-series entry points that end here.
