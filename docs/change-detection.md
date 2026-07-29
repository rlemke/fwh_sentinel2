# Composite + change detection

**Namespace:** `s2.analyze` ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (namespace `s2.analyze`) ·
**Handlers:** `src/sentinel2/handlers/analyze/analyze_handlers.py` ·
**Tools:** `src/sentinel2/tools/_s2_tools/raster.py` ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_mock_chain_end_to_end`, `test_classify_change_method`, `test_water_change_method`, `test_composite_ignores_nodata_nan`, `test_unknown_method_rejected`)

## Overview

`s2.analyze` is the **pure-compute** core: it reduces the per-scene index rasters an
epoch produced into one cloud-robust composite (`Composite`), and compares a
baseline composite to a recent one to emit a change raster + summary stats
(`DetectChange`). It answers "what changed between these two windows, and by how
much." Both facets are `Effect(kind="pure")` — no network, all inputs come from the
cache the source stage filled. The change raster is `loss(-1)/stable(0)/gain(+1)`
for **every** method, which is what lets [change-map](change-map.md) stay
method-agnostic.

## How it works

**`Composite`** → `raster.composite()`. Loads the `scene-index` `.npz` rasters for
the epoch (scoped to `scene_ids` when given, else every cached scene for the
`aoi+index`), `np.stack`s them, and reduces with a **nan-aware** median (default) or
mean — nodata pixels (NaN, set where raw DN was 0) don't vote, so partial scene
coverage over a large AOI doesn't collapse the composite to 0
(`test_composite_ignores_nodata_nan`). Writes one `composite` `.npz` keyed by
`aoi+index+<date_from>_<date_to>`.

**`DetectChange`** → `raster.detect_change()`. Loads the two composites (raising if
their shapes differ), dispatches on `method`, computes loss/gain/total pixel counts,
and writes a `change` `.npz`. Three methods:

- **`difference`** (`_difference_change`) — `delta = recent - base`, thresholded:
  `delta <= -threshold` → loss, `delta >= threshold` → gain.
- **`classify`** (`_classify_change`) — `np.digitize` each epoch into 4 NDVI
  land-cover classes; the change is the **sign of the class shift** (greening = +1,
  browning = -1); `class_counts` carries per-epoch class histograms **and** the
  from→to transition matrix.
- **`water`** (`_water_change`) — for a water index (`index="ndwi"`): threshold each
  epoch into a water mask (`index > threshold`); water→land = receded (loss),
  land→water = flooded (gain); `class_counts` carries per-epoch water-pixel counts +
  net `water_change_pct`.

## Fan-out

**Single-task — no fan-out.** Both are reduces/compares over the whole AOI in one
process. The parallelism they depend on happened upstream in
[fan-out](fan-out.md); `Composite` is ordered behind it with `after`.

## Data & fields

- **Land-cover classes** (`classify`): `NDVI_CLASS_BREAKS = (0.0, 0.2, 0.4)` →
  `NDVI_CLASS_NAMES = ("water", "built_bare", "sparse_veg", "dense_veg")`, monotonic
  by greenness so class index up = greening. Tests assert
  `sum(baseline.values()) == total_pixels` and that every `transitions` key is a
  cross-class `a->b`.
- **Change codes:** `-1` loss, `0` stable, `+1` gain (`int8`), uniform across
  methods.
- **`DetectChange` returns:** `relative_path`, `aoi_key`, `method`, `changed_pixels`,
  `total_pixels`, `pct_loss`, `pct_gain`, `class_counts` (Json), `size_bytes`,
  `sha256`. `class_counts` shape varies by method (histograms+transitions for
  classify; water-pixel counts+`water_change_pct` for water; loss/gain/stable for
  difference).
- **`Composite` returns** the `RasterResult` shape (`scene_count` = # scenes
  reduced, etc.). An unknown `method` or an empty scene set raises (`ValueError` /
  `FileNotFoundError` "run ScanScenes first").

## External libraries / binaries

- **`numpy`** (core dep) — the only dependency: `np.stack`, `np.nanmedian` /
  `np.nanmean`, `np.digitize`, boolean-mask counts. No network, no GDAL, no geo
  extra needed — the analysis stage runs even in the bare (mock/offline) env.

## Facets & workflows

| Facet | Kind | Effect / Cost | Purpose |
|---|---|---|---|
| `Composite(aoi, date_from, date_to, scene_ids: Json, index="ndvi", reducer="median", use_mock=false) => (RasterResult fields)` | event | pure / moderate | Median/mean composite over an epoch's cached scene rasters |
| `DetectChange(baseline_path, recent_path, aoi_key, method="difference", threshold=0.15, use_mock=false) => (relative_path, aoi_key, method, changed_pixels, total_pixels, pct_loss, pct_gain, class_counts: Json, size_bytes, sha256)` | event | pure / cheap | Compare two composites → loss/stable/gain change raster + stats |

Callers write `Composite(…) after <scan>` so the runtime sequences it after the
whole `ScanScenes` fan-out. Neither carries `RetryPolicy` (no network).

## Cache / output

- **Cache type `composite`** — `$FW_CACHE_ROOT/s2/composite/<aoi_key>/<index>/<date_from>_<date_to>.npz`.
- **Cache type `change`** — `$FW_CACHE_ROOT/s2/change/<aoi_key>/<method>.npz`.
- Each `.npz` carries `data` + `bounds` + `crs`; a `.meta.json` sidecar records
  `source` (e.g. `"median of 5 scenes"`, `"classify(ndvi-classes)"`) and sha256.
- Content-addressed reuse: changing `method`/`threshold`/`index` re-uses every
  already-fetched scene raster — only the (cheap) reduce re-runs. Local or S3 per
  `FW_STORAGE`.

## Gotchas & notes

- **NaN-as-nodata is deliberate** — a `0` here would drag the median toward 0 for
  pixels only some scenes cover. Pixels no scene covers stay NaN (→ not water in a
  mask); `nanmedian` emits an expected all-NaN-slice RuntimeWarning that is silenced.
- **Epoch separation is by `scene_ids`, not by cache path** — baseline and recent
  composites share the `aoi+index` namespace, so always pass each epoch's own
  `scene_ids` (the workflows thread `base_search.scene_ids` / `recent_search.scene_ids`).
- **`classify` is an interpretable threshold classifier over a single veg index.**
  The FFL docstring and code both flag the drop-in upgrade: a trained random-forest
  over the full spectral stack (would require caching multiple bands per scene + a
  fitted model). Don't mistake it for a trained land-cover model.
- **Composite shape mismatch raises** — guards against a stale scene raster read at a
  different `MAX_SIZE`; keep `FW_S2_MAX_SIZE` stable across a run.

## Related specs

- [source-adapters](source-adapters.md) — produces the `scene-index` rasters reduced here.
- [fan-out](fan-out.md) — the parallelism `Composite` sequences after.
- [change-map](change-map.md) — renders the `change` raster this emits.
- [water-timeseries](water-timeseries.md) — consumes the per-year `composite` rasters (water-mask, not `DetectChange`).
