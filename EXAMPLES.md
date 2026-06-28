# Worked examples — lake water over time

These are real runs of the `s2.*` FFL workflows on the Facetwork runtime, using
live Landsat (Microsoft Planetary Computer) + USGS gauge data. Each is submitted
with `scripts/ffl-run` against a runner started with
`scripts/start-runner --example sentinel2-landchange`. `FFL` below is the path to
`src/sentinel2/ffl/sentinel2_landchange.ffl`.

## Workflows

| Workflow | What it does |
|----------|--------------|
| `s2.workflows.AnalyzeAOI` | Baseline vs recent change for a raw AOI (NDVI/NDWI/NDBI; difference/classify/water) → MapLibre map. |
| `s2.workflows.AnalyzeRegion` | Geocode a place → `AnalyzeAOI`. |
| `s2.workflows.WaterTimeSeries` | Per-year water **extent** composites (fan-out) → year-tab viewer + area chart. |
| `s2.workflows.WaterLevelTimeSeries` | `WaterTimeSeries` **+** auto-discovered USGS gauge **level** (height, ft), overlaid on a dual-axis chart. |
| `s2.workflows.WaterStorageTimeSeries` | `WaterTimeSeries` **+** USGS reservoir **storage** (quantity, acre-feet), overlaid — the "how much water" axis. |

The three "risen/fallen" measures: **extent** = footprint (km², satellite),
**level** = surface height (ft, gauge), **storage** = quantity (acre-feet, gauge).

Tools (`tools/`) expose the same library functions as CLIs: `search_scenes`,
`find_lake_gauge`, `lake_level`, `reservoir_storage` (see `tools/README.md`).

## The water level / storage vs. extent studies

`WaterLevelTimeSeries` overlays lake **level** (USGS gauge — surface *height*),
and `WaterStorageTimeSeries` overlays reservoir **storage** (USGS — water
*quantity*, acre-feet), on water **extent** (satellite — surface *footprint*). The
gauge is auto-discovered from the place name (`s2.level.ResolveLakeGauge`); pass
`site_id` to override. Five lakes map out what the method can and can't do — and
which of the three measures actually carries the signal for each.

### 1. Great Salt Lake, Utah — the ideal case

```bash
scripts/ffl-run "$FFL" --workflow s2.workflows.WaterLevelTimeSeries \
  --inputs '{"place":"Great Salt Lake, Utah","buffer_km":20,"years":["2004","2009","2014","2019","2022","2024"],
             "collection":"landsat-c2-l2","index":"ndwi","water_threshold":0.0,"max_cloud":25}' --task-list s2
```

Gauge `10010000` (Saltair, ft NGVD29). A **flat-pan** lake: a ~6 ft level drop
bares hundreds of km², so extent and level track tightly — both bottom out
together at the **2022 record low** and recover by 2024. Extent corroborates the
gauge.

### 2. Lake Okeechobee, Florida — marsh-limited, needs tuning

```bash
scripts/ffl-run "$FFL" --workflow s2.workflows.WaterLevelTimeSeries \
  --inputs '{"place":"Lake Okeechobee, Florida","buffer_km":0,"years":["2004","2009","2014","2019","2022","2024"],
             "collection":"landsat-c2-l2","index":"mndwi","months_from":"01-01","months_to":"04-30",
             "water_threshold":0.0,"max_cloud":20}' --task-list s2
```

Gauge `02276400` (ft NGVD29). Needs the turbid-water tuning: **`mndwi`** (green vs
SWIR) for sediment-laden water, a **dry-season window** (Florida: Jan–Apr) to cut
clouds, **`buffer_km=0`** to fit the AOI, and `FW_S2_MAX_SIZE=1024` on the runner
for ~58 m/px. **Ceiling:** ~half the lake is emergent **marsh** that no optical
water index counts as water, so extent tops out near ~520 of ~1,700 km² — a lower
bound that tracks the gauge trend, not the full footprint.

### 3. Clear Lake, California — steep-shored + bloom-limited

```bash
scripts/ffl-run "$FFL" --workflow s2.workflows.WaterLevelTimeSeries \
  --inputs '{"place":"Clear Lake, California","buffer_km":0,"years":["2004","2009","2014","2019","2022","2024"],
             "collection":"landsat-c2-l2","index":"mndwi","water_threshold":0.0,"max_cloud":20,
             "exclude_platforms":"LE07"}' --task-list s2
```

Gauge `11450000` (gage height, ft — the historic "Rumsey" datum; resolved via the
`00065` param). California's clear season is **summer**, so the default Jul–Sep
window is right. `exclude_platforms="LE07"` drops **Landsat-7** scenes whose
SLC-off scan gaps otherwise stripe the composite. **Finding:** a steep-shored
natural lake — its level swings ~7 ft but its footprint is **flat** (~45–50 km²),
so here the *gauge* is the meaningful signal and extent correctly doesn't move.
**Ceiling:** summer cyanobacteria blooms read as not-water, so extent under-counts
(~28% of ~176 km²).

### 4. Lake Powell, Utah/Arizona — canyon reservoir, the drought recession

```bash
# FW_S2_MAX_SIZE=1024 on the runner (large AOI). ~141 reads — a long run.
scripts/ffl-run "$FFL" --workflow s2.workflows.WaterLevelTimeSeries \
  --inputs '{"place":"Lake Powell, Utah","buffer_km":0,"years":["2004","2009","2014","2019","2022","2024"],
             "collection":"landsat-c2-l2","index":"ndwi","water_threshold":0.0,"max_cloud":20,
             "exclude_platforms":"LE07"}' --task-list s2
```

Gauge `09379900` (Glen Canyon Dam, ft NAVD88). A deep **branching canyon
reservoir** — clear water, desert-clear summers, so plain `ndwi` works. Its fitted
bbox is **~113×119 km** (the whole canyon system across several Landsat path/rows)
— the case that forced the **nan-aware composite** (uncovered pixels must not vote
0) and the **index clip** to `[-1,1]`. **Finding:** like the Great Salt Lake but a
reservoir — extent tracks level. The Colorado-River megadrought shows clearly:
open water fell from a **2009 peak (353 km²) to a 2022 low (181 km², −49%)** and
partially recovered by 2024 (252 km²); the side-canyons visibly shrink to threads
in 2022. Where the gauge has data the two move together (3618 ft→322 km²,
3534 ft→181 km², 3582 ft→252 km²). **Caveat:** the USGS `62614` record for this
site is sparse before ~2015, so the level overlay is strongest in recent years.

### 5. Milford Lake, Kansas — storage (the "how much water" axis)

```bash
scripts/ffl-run "$FFL" --workflow s2.workflows.WaterStorageTimeSeries \
  --inputs '{"place":"Milford Lake, Kansas","buffer_km":0,"years":["2004","2009","2014","2019","2022","2024"],
             "collection":"landsat-c2-l2","index":"mndwi","water_threshold":0.0,"max_cloud":20,
             "exclude_platforms":"LE07"}' --task-list s2
```

Gauge `06857050`, USGS param **00054 = storage in acre-feet** (auto-discovered by
passing `params="00054"`). A **flood-control reservoir**: the Corps holds the
surface near conservation pool, so **extent is nearly flat (~62 km²)** while
**storage swings 2.5×** — 332,000 ac-ft (2022 drought) to 849,000 ac-ft (2019
Kansas flood, the one year extent also jumps, to 77 km²). **Finding:** here
neither footprint nor height alone tells you how much water is present — the
*quantity* (storage) carries the signal, and it's the literal answer to "how much
has it risen or fallen." **Coverage:** USGS-gauged reservoirs (Army-Corps / state
lakes) report 00054; Reclamation reservoirs (Powell, Mead) don't — use elevation
or a USBR feed for those.

## What the five lakes teach

| Lake | Shore / form | Signal that carries | Optical ceiling |
|------|--------------|---------------------|-----------------|
| Great Salt Lake | flat pan | extent ↔ level (coupled) | none — clear open water |
| Lake Powell | branching canyon reservoir | extent ↔ level (recession) | none; level record sparse pre-2015 |
| Okeechobee | marsh-fringed | extent (open-water core only) | emergent marsh (~⅓ uncounted) |
| Clear Lake | steep banks | level (footprint flat) | algal blooms under-count |
| Milford Lake | flood-control reservoir | **storage** (extent flat, level alone misleads) | n/a — storage is the measure |

**Extent-tuning levers** (no code change except the resolution env): `index`
(`mndwi` for turbid), `months_from`/`months_to` (region's clear season),
`buffer_km=0` (fit AOI), `FW_S2_MAX_SIZE` (resolution), `exclude_platforms`
(drop Landsat-7 striping). Beyond these, optical water indices map **open water,
not marsh or bloom-covered water** — the full footprint of such lakes needs
land-cover classification or a published lake mask, not index tuning.

## Run from the catalog (no file)

These workflows are published in the Claude workflow catalog, so they run by
slug — `fw_catalog_run` pins a revision and submits to the runtime (dashboard
-visible). One shared library holds the FFL; each workflow is a thin entry
pinned to it.

| Slug | Entry workflow | Answers |
|------|----------------|---------|
| `s2.water-extent-timeseries` | `WaterTimeSeries` | footprint (km²) over the years |
| `s2.water-level-vs-extent` | `WaterLevelTimeSeries` | level (ft, gauge) vs extent |
| `s2.reservoir-storage-vs-extent` | `WaterStorageTimeSeries` | **storage (acre-feet) vs extent — the "how much water" axis** |
| `s2.landchange-lib` | *(library)* | shared facets + workflows the three depend on |

```text
# storage (quantity) for a USGS-gauged reservoir — gauge auto-discovered by name
fw_catalog_run slug="s2.reservoir-storage-vs-extent" inputs={
  "place": "Milford Lake, Kansas",
  "years": ["2004","2009","2014","2019","2022","2024"]
}
```

Discover by intent first with `fw_catalog_match` ("how much water does a
reservoir hold over time") → it returns these with each one's `param_schema`
to fill. Reclamation reservoirs (Powell, Mead) don't report storage to USGS —
use `s2.water-level-vs-extent` (elevation) for those.
