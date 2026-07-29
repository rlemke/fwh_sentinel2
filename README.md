# fwh_sentinel2 — Sentinel-2 land-cover change

A standalone, pip-installable Facetwork example: detect **land-cover change from
Sentinel-2 imagery** between two time windows over an area of interest (AOI), and
render the result as a tiled MapLibre map. Built on open data and open algorithms;
shows off Facetwork's per-scene fan-out, content-addressed caching, and the
source-adapter shape.

Discovered by the Facetwork runner via the `facetwork.domains` entry point — no
edits to the Facetwork repo required.

> **Worked examples:** see [`EXAMPLES.md`](EXAMPLES.md) for end-to-end lake
> water-level-vs-extent studies (Great Salt Lake, Okeechobee, Clear Lake) — the
> FFL workflows, the `tools/` CLIs, and what each reveals (and its limits).

## FFL at a glance

The pipeline is written in [FFL](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md),
Facetwork's workflow language. A step is `name = Facet(args)`; a step that
references another waits for it, and `ScanScenes` fans the per-scene work out
across the fleet:

```ffl
namespace my.s2 {

    use s2.source
    use s2.scan
    use s2.analyze

    /** One epoch: search scenes, fan out per scene, reduce to a composite. */
    workflow OneComposite(aoi: String = "-122.55,37.70,-122.35,37.85",
        date_from: String = "2024-06-01", date_to: String = "2024-09-30") => (path: String, scenes: Int) andThen {

        search = s2.source.SearchScenes(
            aoi = $.aoi, date_from = $.date_from, date_to = $.date_to, max_cloud = 20.0)

        scan = s2.scan.ScanScenes(scene_ids = search.scene_ids, aoi = $.aoi, index = "ndvi")

        comp = s2.analyze.Composite(
            aoi = $.aoi, date_from = $.date_from, date_to = $.date_to,
            scene_ids = search.scene_ids, index = "ndvi", reducer = "median"
            ) after scan

        yield OneComposite(path = comp.relative_path, scenes = comp.scene_count)
    }
}
```

```bash
fw ffl run --primary my.ffl --library src/sentinel2/ffl/sentinel2_landchange.ffl \
  --workflow my.s2.OneComposite
```

📖 **[docs/ffl-examples.md](docs/ffl-examples.md)** — the full example gallery:
two epochs in parallel then compare, writing your own fan-out, nested fan-out over
years, overriding this domain's own `RetryPolicy` mixin at a call site, `catch`,
and `when` guards on cloud cover. Every snippet there is compile-checked.

## Feature specifications

Per-feature specs live in [`docs/`](docs/README.md) — one document per feature, each
covering how it works, fleet fan-out, data/fields, external libraries, facets &
workflows, and cache/output. Start with [**workflows**](docs/workflows.md) (the
flagship — the pipelines you actually run).

| Spec | What it covers |
|------|----------------|
| [workflows](docs/workflows.md) | **Flagship** — the entry-point compositions (`AnalyzeAOI`/`AnalyzeRegion` + the `WaterTimeSeries` family). |
| [source-adapters](docs/source-adapters.md) | `s2.source` — STAC search + COG index read; Sentinel-2 / Landsat provider routing. |
| [change-detection](docs/change-detection.md) | `s2.analyze` — median composite + `difference`/`classify`/`water` change detection. |
| [change-map](docs/change-map.md) | `s2.render` — change raster → GeoTIFF + XYZ tiles + MapLibre viewer. |
| [fan-out](docs/fan-out.md) | `foreach` fleet parallelism — per-scene (`ScanScenes`) and per-year (`ScanYears`). |
| [water-timeseries](docs/water-timeseries.md) | `s2.timeseries` — multi-year water viewer (year slider + area chart + gauge overlay). |
| [gauges](docs/gauges.md) | `s2.level` — USGS level, gauge auto-discovery, USGS + USBR reservoir storage. |
| [geocoding](docs/geocoding.md) | `s2.geo` — Nominatim place name → AOI bbox. |
| [cache-and-storage](docs/cache-and-storage.md) | Local-or-S3 backend + per-entry sidecar cache. |

See [`docs/README.md`](docs/README.md) for the full index.

## Install

```bash
pip install -e .                 # mock path only (offline)
pip install -e ".[geo]"          # + real STAC search & COG reads (requests, rio-tiler)
pip install -e ".[geo,landsat]"  # + Landsat C2 L2 via Planetary Computer (planetary-computer) — ~1984+
pip install -e ".[geo,s3]"       # + write cache/output to S3/MinIO (boto3)
```

### Storage (local or S3)

All I/O goes through `_s2_tools/storage.py`. Default is local disk
(`$FW_CACHE_ROOT`, `$FW_OUTPUT_BASE` / `~/afl_data`). Set `FW_STORAGE=s3`
(+ `FW_DATA_ROOT=s3://<bucket>` and the usual `FW_S3_*` endpoint/creds) and the
cache lands at `s3://<bucket>/cache/s2/…` and the rendered map bundle at
`s3://<bucket>/output/s2/…` — which the dashboard's `/output/raw` artifact server
serves directly (point it at the same prefix with `FW_S3_OUTPUT_BASE`). So a
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
in `$FW_CACHE_ROOT/s2/`, so changing the threshold/method/epoch re-uses everything
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

### Water level vs. extent (`WaterLevelTimeSeries`)

Water *extent* (NDWI) is the lake's **footprint** (km², from the satellite); water
*level* is its **surface height** (ft, from a gauge — not the satellite). They
track, but **non-linearly**: the Great Salt Lake is a flat pan, so a ~6 ft level
drop bares hundreds of km². `s2.workflows.WaterLevelTimeSeries` runs the same
per-year extent fan-out **and** fetches the lake's **USGS NWIS** daily elevation
(`s2.level.FetchLakeLevel`, free, no auth — *US gauges only*), then overlays both
on one **dual-axis** chart (level left, area right) with the year tab bar. Over
2004→2024 on the Great Salt Lake the two bottom out together in **2022** (gauge
4190.0 ft, extent its minimum) and recover by 2024 — an independent gauge
corroborating the satellite.

The gauge is **auto-discovered** for the place (`s2.level.ResolveLakeGauge`): it
searches USGS for lake/reservoir (`siteType=LK`) elevation gauges in the AOI and
picks the one whose station name best matches `place`, else the nearest (flagged
`confident=false`). So *any* US lake with a USGS gauge works by name — Lake Powell
→ `09379900`, Lake Okeechobee → `02276400`, Great Salt Lake → `10010000`. Pass
`site_id` to override; lakes with **no** USGS gauge (e.g. Bureau-of-Reclamation
reservoirs like **Lake Mead**) fail with a clear message — supply a `site_id` or
drop the level overlay.

```bash
# any US lake by name — the gauge is found automatically
scripts/ffl-run "$FFL" --workflow s2.workflows.WaterLevelTimeSeries \
  --inputs '{"place":"Lake Okeechobee, Florida","buffer_km":25,"date_from":"2003-07-01","date_to":"2024-12-31","years":["2004","2009","2014","2019","2022","2024"],"collection":"landsat-c2-l2","water_threshold":0.0,"max_cloud":25,"use_mock":false}' --task-list s2
```

> A gauge measures one point (e.g. the Great Salt Lake south-arm gauge), while
> the extent AOI may span more (the causeway splits the lake's two arms), so
> don't expect a perfectly monotone area↔height map — the joint 2022 minimum and
> overall trend are the signal. Auto-discovery matches on the **place name**, so
> name the lake (`"Great Salt Lake"`), not a feature in it (`"Antelope Island"`),
> for a confident match — or pass `site_id`.

**Tuning extent for a large or turbid lake.** Three levers, no code change except
the resolution env:
> - **`index`**: `"mndwi"` (green vs SWIR) detects turbid/sediment-laden water far
>   better than `"ndwi"` (green vs NIR). Use it for lakes like Okeechobee.
> - **`months_from`/`months_to`**: pick the region's **dry/clear season** (Florida:
>   `01-01`→`04-30`) — fewer clouds → far less year-to-year detection noise.
> - **`buffer_km=0`** fits the AOI to the geocoder's lake bbox (vs an off-center
>   buffer box that clips), and **`FW_S2_MAX_SIZE=1024`** (set on the runner)
>   reads ~58 m/px instead of 115 m (≈2048 ≈ Landsat-native 30 m).
>
> **Ceiling (honest):** optical water indices map **open water**, not emergent
> marsh. Roughly half of Lake Okeechobee is dense littoral marsh, so even tuned
> (fitted bbox + 1024 px + dry-season MNDWI) the extent tops out near ~520 km² of
> its ~1,700 km² — it tracks the gauge's year-to-year trend but is a lower bound
> on the lake's full footprint. Capturing the marsh too needs land-cover
> classification or a published lake mask, not index tuning.

## Run

```bash
# from a Facetwork checkout, after pip install -e:
fw runner start --domain sentinel2-landchange -- --log-format text
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
