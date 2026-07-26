<!-- SPEC TEMPLATE — every docs/<feature>.md follows this shape so the set reads
consistently. Delete this comment in real specs. Keep sections in this order;
omit a section only if it genuinely does not apply (say so in one line rather
than dropping the heading silently). Ground every claim in the actual FFL
docstrings / handler code / tools — do not invent behaviour. -->

# <Feature Name>

**Namespace(s):** `s2.<ns>` · **FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` ·
**Handlers:** `src/sentinel2/handlers/<dir>/*.py` · **Tools:** `src/sentinel2/tools/_s2_tools/<...>.py`

## Overview
One or two paragraphs: what this feature is for, the request it answers, and where
it sits in the pipeline (search → fetch → composite → change → render, etc.).

## How it works
The algorithm / data flow, step by step. Name the concrete steps and the shape of
the data at each (STAC scene ids → per-scene `.npz` index raster → composite →
change raster → XYZ tiles + HTML). If there is a source-adapter split (extraction
vs analysis), say so.

## Fan-out
Does it fan out across the fleet? If yes: what is the fan-out unit (per-scene /
per-year), which facet drives it (a `foreach` over what list), and why it reduces
wall-clock. If it is single-task, say "single-task — no fan-out" and why (e.g. one
reduce over a cache, or an atomicity requirement).

## Data & fields
What data it reads/produces and on which fields — be specific (spectral bands
`red`/`nir08`/`green`/`swir16`; indices `ndvi`/`ndwi`/`mndwi`/`ndbi`; the change
codes loss(-1)/stable(0)/gain(+1); USGS param codes `62614`/`00054`; the
`RasterResult` / `SceneRef` schema fields). Name the mechanism (a rio-tiler window
read, a `np.nanmedian` reduce, a `np.digitize` classifier, a STAC `eo:cloud_cover`
query, a USGS RDB parse). If the feature does no filtering, say so.

## External libraries / binaries
Every non-stdlib dependency this feature relies on and what for — `numpy`,
`requests`, `rio-tiler` (pulls `rasterio` + `morecantile`), `planetary-computer`
(SAS-signing Landsat assets), `boto3` (S3/MinIO), `PyYAML`. Distinguish a **pip**
dependency from an optional extra (`[geo]`/`[landsat]`/`[s3]`), and note where a
missing lib triggers a documented fallback (e.g. the canvas map without rio-tiler).

## Facets & workflows
The key event facets and workflows, with signatures and a one-line purpose taken
from the FFL docstrings. Mark event facets (need a handler) vs pure facets /
workflows, and note `Effect`/`Cost`/`RetryPolicy` mixins where present.

## Cache / output
The cache namespace under `$FW_CACHE_ROOT/s2/<cache_type>/` and the cache type
(`scene-index` / `composite` / `change` / `lake-level`), plus the output
artifact(s) and format (`.npz` raster, `change.tif` GeoTIFF, XYZ PNG pyramid,
MapLibre `index.html`). Note the `.meta.json` sidecar, and whether outputs go to
local disk or S3/MinIO (`FW_STORAGE=s3`).

## Gotchas & notes
Known pitfalls, rate limits, sensitivity caveats, or non-obvious constraints
(fixed output grid for stacking, NaN-as-nodata, provider auto-routing by scene id,
Nominatim 1 req/s, optical-water ceiling on marsh, US-only gauges — anything a
future maintainer would trip on).

## Related specs
Links to the specs this feature composes with or depends on.
