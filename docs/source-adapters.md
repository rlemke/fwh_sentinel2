# Source adapters — STAC search + COG index read

**Namespace:** `s2.source` ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (namespace `s2.source`) ·
**Handlers:** `src/sentinel2/handlers/source/source_handlers.py` ·
**Tools:** `src/sentinel2/tools/_s2_tools/{stac,raster,s2_mocks}.py` ·
**CLI:** `src/sentinel2/tools/search_scenes.py` (`search_scenes.sh`) ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_provider_routing`, `test_real_stac_search_live`, `test_real_landsat_read_live`, `test_mndwi_index`)

## Overview

`s2.source` is the **extraction** half of the source-adapter shape: it turns a raw
area-of-interest bbox + date window into analysis-ready single-band index rasters,
without the downstream `s2.analyze` / `s2.render` code caring where the pixels came
from. It answers "which scenes cover this box in this window, and give me their
NDVI/NDWI over the AOI." Two facets: `SearchScenes` (query a STAC catalog for scene
ids) and `FetchSceneIndex` (window-read one scene's bands and cache its computed
index). The FFL header states the intent explicitly: `s2.analyze` and `s2.render`
are source-agnostic, so a future `s2.source.Landsat` / `PlanetaryComputer` feeds
the same composite/change/render path — in fact Landsat is already wired in here
(see Provider routing).

## How it works

1. **`SearchScenes`** → `stac.search()` (`stac.py`). POSTs a STAC `/search` to the
   collection's provider endpoint with `bbox`, a `datetime` range, and a
   `query: {eo:cloud_cover: {lt: max_cloud}}` filter, paging `next` links up to
   `_MAX_PAGES=20` × `_PAGE_LIMIT=100`. Returns scene dicts `{scene_id, datetime,
   cloud_pct}`; the handler flattens them to `scene_ids` (a Json array) + `count`.
2. **`FetchSceneIndex`** → `raster.fetch_scene_index()` (`raster.py`). For a cache
   miss, resolves the two index bands' asset hrefs (`stac.get_item_assets`),
   window-reads each over the AOI with a rio-tiler `Reader.part(...)` at a **fixed
   output grid** (`_grid_size(bbox, MAX_SIZE)`), converts raw DN → surface
   reflectance (`raw * scale + offset`), computes the normalized-difference index,
   clips to `[-1, 1]`, and caches the array as `.npz`. Idempotent: a hit returns
   `was_cached=True` without touching the network.

Data shape: `AOI + window → scene_ids (Json) → per-scene index raster (.npz)`. The
per-scene rasters land in the shared cache for `s2.analyze.Composite` to reduce.

## Fan-out

**`SearchScenes` and `FetchSceneIndex` are each single-task.** The fan-out over
scenes lives one layer up in `s2.scan.ScanScenes`, which `foreach`-es
`FetchSceneIndex` across the fleet — one parallel step per scene id. See
[fan-out](fan-out.md). `SearchScenes` is intentionally one task (a single paged
HTTP query); `FetchSceneIndex` is the per-unit worker the fan-out multiplies.

## Data & fields

- **Spectral bands** (`raster._BANDS`), as `(numerator, denominator)` for a
  normalized-difference index: `ndvi=(nir,red)`, `ndwi=(green,nir)`,
  `mndwi=(green,swir16)`, `ndbi=(swir16,nir)`. `mndwi` (green vs SWIR) detects
  turbid / sediment-laden water far better than `ndwi` — used for lakes like
  Okeechobee. An unknown index raises `ValueError` (`test_unknown_index_rejected`).
- **STAC filter fields:** `bbox`, `datetime` (`<from>T00:00:00Z/<to>T23:59:59Z`),
  `eo:cloud_cover < max_cloud`. `exclude_platforms` is a comma-separated list of
  scene-id prefixes dropped post-query (`_drop_platforms`) — e.g. `"LE07"` to skip
  Landsat-7, whose SLC-off gaps stripe the composite (`test_exclude_platforms`).
- **`SceneRef` schema** (`s2.types`): `scene_id`, `datetime`, `cloud_pct`,
  `cog_href`. **`RasterResult` schema**: `cache_type`, `relative_path`, `aoi_key`,
  `index`, `scene_count`, `width`, `height`, `size_bytes`, `sha256`, `was_cached`,
  `used_mock` — the shape every `FetchSceneIndex`/`Composite` returns.
- **Nodata handling:** raw `0` pixels → `NaN` (not 0) so partial scene coverage
  doesn't drag the composite median toward zero (the `nanmedian` in
  [change-detection](change-detection.md) drops them).

### Provider routing (Sentinel-2 vs Landsat)

`stac.PROVIDERS` holds two entries, chosen by `provider_for(scene_id, collection)`:

| Collection | Endpoint | Bands (nir key) | SR scale/offset | Signed? |
|---|---|---|---|---|
| `sentinel-2-l2a` | Element84 Earth Search (AWS Open Data), ~2017+ | `nir` | `1e-4` / `0` | no — anonymous AWS (`AWS_NO_SIGN_REQUEST=YES`) |
| `landsat-c2-l2` | Microsoft Planetary Computer, ~1984+ | `nir08` | `2.75e-5` / `-0.2` | yes — SAS-signed Azure blobs |

A **scene id beginning with `L` wins** regardless of the `collection` arg, so a
`FetchSceneIndex` step that only carries the id still routes to Planetary Computer +
signing (`test_provider_routing`). Indices are computed on surface reflectance so
the two sensors are comparable across a multi-decade series. AWS's requester-pays
`usgs-landsat` copy is deliberately not used.

## External libraries / binaries

- **`requests`** (pip, `[geo]` extra) — the STAC search and item-asset lookups.
- **`rio-tiler`** (pip, `[geo]`; pulls `rasterio` + `morecantile`) —
  `rio_tiler.io.Reader.part(...)` window-reads the COG bands; the read runs inside
  a per-provider `rasterio.Env(**gdal_env)` (anonymous AWS for S2, plain
  `/vsicurl` for signed Azure).
- **`planetary-computer`** (pip, `[landsat]` extra) — `pc.sign(href)` signs Landsat
  asset URLs; imported lazily only when `provider["sign"]` is true.
- **`numpy`** (core dep) — the index math and array persistence.
- No system binaries. The mock path (`s2_mocks.py`) needs none of the geo stack.

## Facets & workflows

| Facet | Kind | Effect / Cost | Purpose |
|---|---|---|---|
| `SearchScenes(aoi, date_from, date_to, max_cloud=20.0, collection="sentinel-2-l2a", stac_url="", exclude_platforms="", use_mock=false) => (count: Int, scene_ids: Json)` | event | external / moderate | STAC query for scenes intersecting the AOI under a cloud ceiling |
| `FetchSceneIndex(scene_id, aoi, index="ndvi", force=false, use_mock=false) => (RasterResult fields)` | event | external / moderate | Window-read + compute + cache one scene's AOI-clipped index raster |

Both carry `with RetryPolicy()` (`s2.mixins.RetryPolicy(max_retries=4,
backoff_ms=2000)`) — the STAC search and COG reads hit remote object stores that
occasionally 5xx/throttle.

## Cache / output

- **Cache type `scene-index`** under `$FW_CACHE_ROOT/s2/scene-index/<aoi_key>/<index>/<scene_id>.npz`.
  The `.npz` holds `data` (float32 index array) + `bounds` (lon/lat) + `crs`; a
  `.meta.json` sidecar records size/sha256/source/tool (see
  [cache-and-storage](cache-and-storage.md)). `aoi_key(aoi)` filesystem-encodes the
  bbox (`,`→`_`, `-`→`m`, `.`→`p`).
- No user-facing output artifact — this feature only populates the cache the
  analysis stages consume. Local disk or S3/MinIO per `FW_STORAGE`.

## Gotchas & notes

- **Fixed output grid is load-bearing.** `MAX_SIZE` (env `FW_S2_MAX_SIZE`, default
  512) is read once at import, and `_grid_size` derives an exact `(w, h)` per AOI so
  every scene of that AOI reads to identical dimensions — otherwise `Composite`'s
  `np.stack` sees off-by-one shapes (`test_grid_size_exact_and_consistent`). Raise
  `FW_S2_MAX_SIZE` to ~1024/2048 for large lakes (~58 m / 30 m native px).
- **`--aoi=` on the CLI:** a leading-minus bbox looks like a flag, so use
  `--aoi=-122.55,...` (documented in `tools/README.md`).
- **Landsat needs the extra:** reading (not just searching) Planetary Computer
  requires `pip install -e ".[geo,landsat]"`; without it the sign import fails.
- The `search_scenes` CLI is the shipped reference; a `fetch_scene_index` CLI is
  a documented TODO (`tools/README.md`) — the library + handler already exist.

## Related specs

- [fan-out](fan-out.md) — `ScanScenes` multiplies `FetchSceneIndex` per scene.
- [change-detection](change-detection.md) — reduces these per-scene rasters into composites + change.
- [cache-and-storage](cache-and-storage.md) — the `.npz` + sidecar cache these write.
- [workflows](workflows.md) — the entry-point pipelines that call `SearchScenes` twice (baseline + recent) per run.
