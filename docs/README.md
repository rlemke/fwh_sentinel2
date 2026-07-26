# Sentinel-2 land-cover change — Feature Specifications

This directory holds one **spec per feature** of the `fwh_sentinel2` domain. Each
document follows a common shape ([`SPEC_TEMPLATE.md`](SPEC_TEMPLATE.md)) and states,
for that feature: how it works, whether and how it **fans out** across the fleet, the
**data & fields** it reads/produces (spectral bands, indices, change codes, gauge
params), the **external libraries** it relies on (and which optional extra guards
them), its **facets & workflows** (with `Effect`/`Cost` mixins), and its
**cache/output**. Claims are grounded in the FFL `/** … */` docstrings, the handler
code, and the `_s2_tools` library — the source of truth for each facet remains its FFL
docstring; these specs are the feature-level narrative over them.

**Start here:** [**Composed workflows**](workflows.md) — the flagship. It's the small
set of `andThen` pipelines a user actually runs (`AnalyzeAOI` / `AnalyzeRegion` and the
`WaterTimeSeries` family) and shows how every other feature composes. Worked, live runs
are in [`../EXAMPLES.md`](../EXAMPLES.md).

## Pipeline (source → analysis → render)

| Spec | What it covers |
|------|----------------|
| [workflows.md](workflows.md) | **Flagship.** The entry-point compositions: land-cover change (`AnalyzeAOI`/`AnalyzeRegion`) and the surface-water time-series family (`WaterTimeSeries` + level/storage/USBR variants). |
| [source-adapters.md](source-adapters.md) | `s2.source` — STAC search + COG window-read into a per-scene index raster; provider auto-routing (Sentinel-2 Earth Search vs Landsat Planetary Computer). |
| [change-detection.md](change-detection.md) | `s2.analyze` — nan-aware median composite + change detection (`difference` / `classify` / `water`); the `loss(-1)/stable(0)/gain(+1)` raster. |
| [change-map.md](change-map.md) | `s2.render` — change raster → `change.tif` + XYZ PNG pyramid + MapLibre viewer (with a canvas fallback when the geo stack is absent). |

## Fan-out & scale

| Spec | What it covers |
|------|----------------|
| [fan-out.md](fan-out.md) | The `foreach` fleet parallelism: `ScanScenes` (per scene) and `ScanYears`/`WaterYear` (per year) — the fan-out-of-fan-outs, sequenced via `dependency_signal`. |
| [cache-and-storage.md](cache-and-storage.md) | The local-or-S3 backend + per-entry `.meta.json` sidecar cache (content-addressed, lock-free) shared by the CLI and the runtime. |

## Water time series & inputs

| Spec | What it covers |
|------|----------------|
| [water-timeseries.md](water-timeseries.md) | `s2.timeseries` — the multi-year water viewer: year slider/tab bar + area chart, with an optional dual-axis gauge overlay. |
| [gauges.md](gauges.md) | `s2.level` — USGS NWIS level, gauge auto-discovery by name, USGS reservoir storage, and USBR (Powell/Mead) storage/elevation. |
| [geocoding.md](geocoding.md) | `s2.geo` — Nominatim place name → AOI bbox; `buffer_km` as the fan-out governor. |

---

*See also the machine-readable capability index at
[`../src/sentinel2/catalog.yaml`](../src/sentinel2/catalog.yaml) (workflows + facets by
intent, loaded via `sentinel2.catalog.load_manifest()`), the repo
[`../README.md`](../README.md) and [`../EXAMPLES.md`](../EXAMPLES.md), and the vendored
contracts under [`../agent-spec/`](../agent-spec/). The live/queryable interface is the
MCP `fw_capabilities` / `fw_catalog_match` / `fw_describe_handler` tools.*
