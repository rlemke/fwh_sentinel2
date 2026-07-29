# Composed workflows — the entry points

**Namespace:** `s2.workflows` ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (namespace `s2.workflows`) ·
**Handlers:** none — these are pure FFL compositions over the `s2.*` event facets ·
**Catalog:** `src/sentinel2/catalog.yaml` (reuse-first intent index) ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_ffl_defines_expected_workflows_and_facets`, `test_mock_chain_end_to_end`) ·
**Worked runs:** `EXAMPLES.md`

## Overview

`s2.workflows` is the **flagship** — the small set of `andThen` compositions a user
actually runs. Everything else in this package is a leaf these pipelines wire
together: geocode → search → per-scene fan-out → composite → change/water → render.
There are two families: **land-cover change** (`AnalyzeAOI`, `AnalyzeRegion`) and
**surface-water time series** (`WaterTimeSeries` and its level/storage variants),
plus the shared fan-out building blocks (`WaterYear`, `ScanYears`, and `s2.scan.ScanScenes`).

If you only read one spec, read this — it shows how the [source-adapters](source-adapters.md),
[fan-out](fan-out.md), [change-detection](change-detection.md),
[change-map](change-map.md), [water-timeseries](water-timeseries.md),
[gauges](gauges.md), and [geocoding](geocoding.md) features compose.

## How it works

**Land-cover change.** `AnalyzeAOI` runs, per epoch (baseline + recent):
`SearchScenes → ScanScenes (fan-out) → Composite`, then `DetectChange` (baseline vs
recent) → `ChangeMap`. Each `Composite` is written `after <scan>` so it waits for
its whole fan-out; `ChangeMap` is written `after change` so it waits for the change
step. `AnalyzeRegion` is a thin front: `ResolveAOI(place)`
→ `AnalyzeAOI(aoi = loc.aoi, …)`, yielding the geocoder's `display_name` + bbox in
its `detail`.

**Surface-water time series.** `WaterTimeSeries` runs `ResolveAOI → ScanYears
(per-year fan-out) → WaterTimeSeriesMap`. Each `WaterYear` inside `ScanYears` does its
own `SearchScenes → ScanScenes → Composite` for that year's seasonal window
(fan-out of fan-outs). The three overlay variants add a gauge side-branch parallel to
`ScanYears`, threading its cached-series `relative_path` into the renderer's
`level_relative_path`:

- **`WaterLevelTimeSeries`** — `ResolveLakeGauge` → `FetchLakeLevel` (USGS level, ft).
- **`WaterStorageTimeSeries`** — `ResolveLakeGauge(params="00054")` →
  `FetchReservoirStorage` (USGS storage, acre-feet).
- **`ReservoirStorageUSBR`** — `FetchUSBRStorage(reservoir=place)` (Powell/Mead), no
  gauge-discovery step (USBR keyed by name).

## Fan-out

These workflows **are** the fleet-parallel runs: every one fans out at least per
scene (`ScanScenes`), and the time-series family fans per year on top (`ScanYears` →
`WaterYear` → `ScanScenes`). See [fan-out](fan-out.md). The workflows themselves have
no handler — the runtime executes the `andThen`/`foreach` machinery; the fleet claims
the leaf event-facet steps.

## Data & fields

- **Common knobs:** `aoi`/`place` + `buffer_km`, date windows (`baseline_from`…,
  `recent_from`… or `years` + `months_from`/`months_to`), `index`
  (`ndvi`/`ndwi`/`mndwi`/`ndbi`), `max_cloud`, `method`
  (`difference`/`classify`/`water`), `threshold`/`water_threshold`, `collection`
  (`sentinel-2-l2a` ~2017+ or `landsat-c2-l2` ~1984+), `exclude_platforms`,
  `use_mock`.
- **Yields:** the change workflows yield `status`/`html_path`/`detail` (+ `aoi` for
  `AnalyzeRegion`); the water workflows yield `status`/`html_path`/`aoi`/`year_count`
  (+ `level_points`/`storage_points` + `gauge`/`gauge_confident`/`reservoir` for the
  overlay variants).
- **Metadata mixins:** every entry-point workflow carries `with Author(email=…)` and
  `with Teams(names=["geo","research"])`.

## External libraries / binaries

None directly — pure FFL composition. The dependencies live in the event-facet leaves
(`requests`/`rio-tiler`/`numpy`/`planetary-computer`/`boto3`); see the per-feature
specs. `catalog.py` reads `catalog.yaml` with **`PyYAML`** (a core dep) for the
machine-readable intent index.

## Facets & workflows

| Workflow | Purpose |
|---|---|
| `AnalyzeAOI(aoi, baseline_*, recent_*, index="ndvi", max_cloud=20.0, method="difference", threshold=0.15, use_mock=false) => (status, html_path, detail)` | End-to-end land-cover change for one bbox |
| `AnalyzeRegion(place, buffer_km=10.0, …, method="classify", …) => (status, html_path, detail, aoi)` | Geocode a place → `AnalyzeAOI` (the "show change in \<place\>" entry point) |
| `WaterTimeSeries(place, buffer_km=20.0, years: Json, …, index="ndwi", water_threshold=0.1, collection="sentinel-2-l2a", …) => (status, html_path, aoi, year_count)` | Per-year water extent viewer + area chart |
| `WaterLevelTimeSeries(place, …, site_id="", date_from, date_to, years, …, collection="landsat-c2-l2", …) => (…, level_points, gauge, gauge_confident)` | `WaterTimeSeries` + USGS gauge **level** overlay |
| `WaterStorageTimeSeries(place, …, index="mndwi", exclude_platforms="LE07", …) => (…, storage_points, gauge, gauge_confident)` | `WaterTimeSeries` + USGS reservoir **storage** overlay |
| `ReservoirStorageUSBR(place, …) => (…, storage_points, reservoir)` | Water extent + USBR storage (Powell/Mead) |
| `WaterYear(aoi, year, …) => (relative_path, scene_count)` | Building block: one year's water composite |
| `ScanYears(aoi, years: Json, …) => (count: Long)` | Building block: fan out `WaterYear` per year |

`s2.scan.ScanScenes` (per-scene fan-out) lives in its own namespace — see
[fan-out](fan-out.md). All of the above are workflows (no handler); the leaves they
call carry the `Effect`/`Cost`/`RetryPolicy` mixins documented per-feature.

## Cache / output

The workflows own no cache. Their leaves populate the `scene-index` / `composite` /
`change` / `lake-level` caches and write the map bundle to `output/s2/<aoi_key>/` (or
`output/s2-timeseries/<aoi_key>/`). Re-running is cheap — every scene raster and
composite is content-addressed, so changing `method`/`threshold`/`index`/window reuses
everything already fetched. See [cache-and-storage](cache-and-storage.md).

## Gotchas & notes

- **`use_mock=true` runs the whole chain offline** (geocode included) against
  deterministic fixtures — no network, no GDAL. It's what the default test suite
  exercises; a live path needs `pip install -e ".[geo]"` (and `[landsat]` for
  Landsat).
- **Pick the collection for your time span** — Sentinel-2 starts ~2017; for a true
  multi-decade series pass `collection="landsat-c2-l2"` (Planetary Computer, ~1984+,
  signed assets). The provider auto-routes per scene, so a mixed series stays
  comparable (SR-based indices).
- **`--task-list s2`** — submit these with the `s2` task list so they route to
  `s2.*` runners (the `agent.py` RegistryRunner advertises `topics=["s2.*"]`).
- **Reuse-first before authoring** — `catalog.yaml` indexes these workflows by intent
  (summaries + tags + `param_schema`) so an LLM matches an NL request against them (à
  la `fw_catalog_match`) instead of re-authoring. `sentinel2.catalog.workflows()` /
  `facets()` load it.

## Related specs

- [source-adapters](source-adapters.md) · [fan-out](fan-out.md) ·
  [change-detection](change-detection.md) · [change-map](change-map.md) ·
  [water-timeseries](water-timeseries.md) · [gauges](gauges.md) ·
  [geocoding](geocoding.md) — the leaves these workflows compose.
- [cache-and-storage](cache-and-storage.md) — the content-addressed cache that makes re-runs cheap.
