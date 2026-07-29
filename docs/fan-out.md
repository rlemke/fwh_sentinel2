# Fan-out — per-scene and per-year parallelism

**Namespace:** `s2.scan`, `s2.workflows` (fan-out workflows) ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (`ScanScenes`, `ScanYears`, `WaterYear`) ·
**Handlers:** none — these are pure FFL `foreach` workflows over
`s2.source.FetchSceneIndex` (see [source-adapters](source-adapters.md)) ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_water_timeseries`, `test_mock_chain_end_to_end` build the same fan-out shape inline)

## Overview

This is the fleet-parallelism pattern the whole package rests on. Reading N COG
scenes is embarrassingly parallel, so instead of one runner window-reading every
scene serially, the pipeline `foreach`-es the per-scene fetch into N runtime steps
that any runner advertising `s2.*` can claim. There are two fan-out layers:

- **`s2.scan.ScanScenes`** — one step per **scene** (within one epoch).
- **`s2.workflows.ScanYears`** — one branch per **year**, each of which is itself a
  `WaterYear` → its own `ScanScenes` per-scene fan-out. So a multi-year water study
  is a fan-out of fan-outs.

## How it works

`ScanScenes` is a workflow with a single `andThen foreach`:

```
workflow ScanScenes(scene_ids: Json, aoi, index="ndvi", use_mock=false) => (count: Long)
    andThen foreach sid in $.scene_ids {
        idx = FetchSceneIndex(scene_id = $.sid, aoi = $.aoi, index = $.index, use_mock = $.use_mock)
        yield ScanScenes(count = 1)
    }
```

Each loop iteration becomes an independent runtime step running one
`FetchSceneIndex`; the loop variable is bound on the block's `$` surface and read as
`$.sid` (relative-scoping rule). Every step writes its AOI-clipped raster to the
shared `scene-index` cache, so the downstream `Composite` reduce finds them all.
The `yield ScanScenes(count = 1)` per iteration is a progress counter, not the
ordering mechanism: the caller writes `Composite(…) after base_scan`, so the runtime
schedules the reduce **after** every iteration of the fan-out that produced its
inputs. The clause is required precisely because there is no data edge — scenes flow
through the cache, not the step payload.

`ScanYears` fans `WaterYear` over a `years` Json list; each `WaterYear` runs its own
`SearchScenes → ScanScenes → Composite` for that year's seasonal window, landing one
per-year composite in cache keyed by `aoi+index+window` — exactly what
[water-timeseries](water-timeseries.md)'s renderer discovers.

## Fan-out

**This spec is the fan-out.** Fan-out unit: one step **per scene** (`ScanScenes`),
one branch **per year** (`ScanYears`). Wall-clock: an epoch's ~3–20 scene reads run
concurrently across runners rather than in series; a 6-year series fans into 6
independent year branches on top. All coordination is through MongoDB + the shared
cache — no shared in-process dispatcher.

## Data & fields

- **`scene_ids: Json`** — the array from `SearchScenes` that `ScanScenes` iterates.
- **`years: Json`** — the array `ScanYears` iterates (e.g. `["2017","2019","2022"]`).
- **`count: Long`** — the per-iteration `yield` value, reported for visibility; the
  reduce is ordered by an `after` clause, not by this number.
- No filtering here; `exclude_platforms` filtering happens inside the wrapped
  `SearchScenes` (see [source-adapters](source-adapters.md)).

## External libraries / binaries

None — these workflows are pure FFL orchestration. The libraries live in the
`FetchSceneIndex` / `Composite` steps they drive.

## Facets & workflows

| Workflow | Kind | Purpose |
|---|---|---|
| `ScanScenes(scene_ids: Json, aoi, index="ndvi", use_mock=false) => (count: Long)` | workflow (no handler) | `foreach` fan-out of `FetchSceneIndex` — one parallel step per scene |
| `WaterYear(aoi, year, months_from="07-01", months_to="09-30", index="ndwi", max_cloud=15.0, collection="sentinel-2-l2a", exclude_platforms="", use_mock=false) => (relative_path, scene_count)` | workflow | one year's water composite: search + per-scene fan-out + composite |
| `ScanYears(aoi, years: Json, …) => (count: Long)` | workflow (no handler) | `foreach` fan-out of `WaterYear` — one branch per year |

None carry `Effect`/`Cost` mixins (they are orchestration, not effectful leaves).

## Cache / output

No new cache type of their own. `ScanScenes` populates the `scene-index` cache (via
`FetchSceneIndex`); `WaterYear`/`ScanYears` additionally produce `composite` entries
(via `Composite`). See [cache-and-storage](cache-and-storage.md).

## Gotchas & notes

- **`after` is how the reduce waits.** Because per-scene rasters move through the
  cache and not the step payload, `Composite`/renderers must be sequenced
  explicitly — always write `after <scan>`. Dropping it risks a composite reducing
  over an incomplete scene set.
- **Composite scoping by `scene_ids` separates epochs.** Baseline and recent share
  one `aoi+index` cache namespace; the composite is scoped to *its* epoch's
  `scene_ids` so the two don't reduce over the same mixed set (see
  [change-detection](change-detection.md)).
- **A full-municipality polygon would explode the fan-out.** `s2.geo.ResolveAOI`
  defaults to a `buffer_km` box precisely because a place's true polygon (Apuí
  ~54,000 km²) would fan into hundreds of scenes — see [geocoding](geocoding.md).
- Runners advertise `topics=["s2.*"]` (`agent.py`), so every scene/year step in a
  run is claimable by any `s2` runner in the fleet.

## Related specs

- [source-adapters](source-adapters.md) — the `FetchSceneIndex` unit this multiplies.
- [change-detection](change-detection.md) — the `Composite` reduce that consumes each fan-out's output.
- [water-timeseries](water-timeseries.md) — consumes the `ScanYears` per-year composites.
- [workflows](workflows.md) — where `ScanScenes`/`ScanYears` are composed into entry points.
