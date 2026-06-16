# fwh_sentinel2 — Sentinel-2 land-cover change

A standalone, pip-installable Facetwork example: detect **land-cover change from
Sentinel-2 imagery** between two time windows over an area of interest (AOI), and
render the result as a tiled MapLibre map. Built on open data and open algorithms;
shows off Facetwork's per-scene fan-out, content-addressed caching, and the
source-adapter shape.

Discovered by the Facetwork runner via the `facetwork.examples` entry point — no
edits to the Facetwork repo required.

## Install

```bash
pip install -e .                 # mock path only (offline)
pip install -e ".[geo]"          # + real STAC search & COG reads (requests, rio-tiler)
pip install -e ".[geo,landsat]"  # + Landsat C2 L2 via Planetary Computer (planetary-computer) — ~1984+
pip install -e ".[geo,s3]"       # + write cache/output to S3/MinIO (boto3)
```

### Storage (local or S3)

All I/O goes through `_s2_tools/storage.py`. Default is local disk
(`$AFL_CACHE_ROOT`, `$AFL_OUTPUT_BASE` / `~/afl_data`). Set `AFL_STORAGE=s3`
(+ `AFL_DATA_ROOT=s3://<bucket>` and the usual `AFL_S3_*` endpoint/creds) and the
cache lands at `s3://<bucket>/cache/s2/…` and the rendered map bundle at
`s3://<bucket>/output/s2/…` — which the dashboard's `/output/raw` artifact server
serves directly (point it at the same prefix with `AFL_S3_OUTPUT_BASE`). So a
fleet run renders straight to MinIO and is viewable from the Runs list.

## What it does

Entry workflow **`s2.workflows.AnalyzeAOI`**. For a **baseline** and a **recent**
window:

1. **`s2.source.SearchScenes`** — STAC query for scenes intersecting the AOI under
   a cloud ceiling. Provider is chosen by `collection`: Sentinel-2 L2A via Element84
   Earth Search (AWS Open Data, ~2017+) or Landsat C2 L2 via the Planetary Computer
   (~1984+, signed). See the **Range note** below.
2. **`s2.scan.ScanScenes`** — `andThen foreach` fan-out: one parallel
   **`s2.source.FetchSceneIndex`** step per scene, window-reading the bands (COG
   range requests via rio-tiler), computing a spectral index (NDVI/NDWI/NDBI), and
   caching the AOI-clipped raster.
3. **`s2.analyze.Composite`** — median composite over that epoch's cached scene
   rasters (scoped by `scene_ids`).

Then **`s2.analyze.DetectChange`** — `method`:
- **`difference`** — index delta thresholded into loss / stable / gain.
- **`classify`** — bin each epoch into land-cover classes (water / built-bare /
  sparse-veg / dense-veg by NDVI) and report the per-pixel class transition;
  `class_counts` carries per-class histograms + the from→to transition matrix.
  (Threshold classifier; a trained random-forest over the full spectral stack is
  the drop-in upgrade.)

Both emit the same loss/stable/gain raster, so **`s2.render.ChangeMap`** (a
georeferenced `change.tif` + an XYZ PNG pyramid + a MapLibre viewer over a CARTO
basemap) is method-agnostic. Every scene raster and composite is content-addressed
in `$AFL_CACHE_ROOT/s2/`, so changing the threshold/method/epoch re-uses everything
already fetched.

### Surface water over time (`WaterTimeSeries`)

`s2.workflows.WaterTimeSeries(place, years, index="ndwi", …)` builds one NDWI
water composite per year (a `ScanYears` fan-out over `WaterYear`) and renders a
MapLibre viewer with a **year slider / tab bar** + a water-area (km²) line chart —
scrub the years and watch a lake shrink and recover. Real example (Antelope
Island, Great Salt Lake): water ≈34 km² (2017) → 28 (2019) → 16 (2021) → **9 km²
(2022 record low)** → **103 km² (2024)** after the record snowpack refill.

```bash
scripts/ffl-run "$FFL" --workflow s2.workflows.WaterTimeSeries \
  --inputs '{"place":"Antelope Island, Utah","buffer_km":12,"years":["2017","2019","2021","2022","2024"],"index":"ndwi","water_threshold":0.1,"use_mock":false}' --task-list s2
```

> **Range note.** Sentinel-2 starts ~2017. For a true multi-decade span, pass
> `"collection":"landsat-c2-l2"` — Landsat Collection-2 L2 via the
> [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com) covers
> **~1984→present** (free; asset hrefs are signed with a SAS token, so install
> `".[geo,landsat]"`). The same `WaterTimeSeries`/`AnalyzeAOI` path serves both
> sensors: the provider is chosen per scene (a Landsat scene id auto-routes to
> Planetary Computer + signing), and indices are computed on surface reflectance
> so the two sensors are comparable across the series. AWS's `usgs-landsat` copy
> is requester-pays and is deliberately **not** used. Example — a 20-year Landsat
> water series over the Great Salt Lake:
>
> ```bash
> scripts/ffl-run "$FFL" --workflow s2.workflows.WaterTimeSeries \
>   --inputs '{"place":"Antelope Island, Utah","buffer_km":20,"collection":"landsat-c2-l2","years":["2004","2009","2014","2019","2022","2024"],"index":"ndwi","water_threshold":0.0,"max_cloud":25,"use_mock":false}' --task-list s2
> ```

## Run

```bash
# from a Facetwork checkout, after pip install -e:
scripts/start-runner --example sentinel2-landchange -- --log-format text
scripts/ffl-run $(python -c "import sentinel2,os;print(os.path.join(os.path.dirname(sentinel2.__file__),'ffl','sentinel2_landchange.ffl'))") \
  --workflow s2.workflows.AnalyzeAOI \
  --inputs '{"use_mock": true, "method": "classify"}' --task-list s2
```

Drop `use_mock` (and `pip install -e ".[geo]"`) for the real path. `use_mock=true`
runs the whole chain offline against deterministic fixtures (no network/GDAL) —
that's what the default test suite exercises; a live STAC test is opt-in
(`S2_LIVE=1 pytest -k live`).

## Layout

```
src/sentinel2/
  ffl/sentinel2_landchange.ffl   namespaces / schemas / facets / workflows
  handlers/                      source / analyze / render dispatchers + shared/ shim
  tools/_s2_tools/               stac, raster, map_render, sidecar, storage, mocks
  tools/search_scenes.py(.sh)    reference CLI
tests/                           FFL compile + offline mock e2e + classify + dispatch
agent.py                         standalone RegistryRunner entry point
agent-spec/                      vendored tools-pattern + cache-layout contracts
```

Follows `agent-spec/tools-pattern.agent-spec.yaml` — one code path behind the CLI
and the FFL handlers, a per-entry `.meta.json` cache sidecar, and a
package-unique `_s2_tools/` lib.
