# Change map — MapLibre tiled viewer

**Namespace:** `s2.render` ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (namespace `s2.render`) ·
**Handlers:** `src/sentinel2/handlers/render/render_handlers.py` ·
**Tools:** `src/sentinel2/tools/_s2_tools/map_render.py` ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_mock_chain_end_to_end` — asserts the HTML, the XYZ tiles, and `change.tif`)

## Overview

`s2.render.ChangeMap` is the presentation stage: it turns the
`loss(-1)/stable(0)/gain(+1)` change raster from [change-detection](change-detection.md)
into a real web map — a georeferenced GeoTIFF, an XYZ PNG tile pyramid, and a
MapLibre GL HTML viewer that loads those tiles over a CARTO basemap (loss in red,
gain in green). Because the change raster is method-agnostic, the same renderer
serves the `difference`, `classify`, and `water` methods without change.

## How it works

`map_render.render_change_map()` has a **preferred tiled path and a fallback**:

1. **Tiled (rio-tiler present)** — `_render_tiles()` colorizes the `int8` change
   grid to a 3-band RGB array + a visibility mask (stable/nodata transparent),
   writes a deflate-compressed `change.tif` via `rasterio` (staged in a temp dir,
   then published through `storage`), and slices an XYZ pyramid with a `morecantile`
   `WebMercatorQuad` TMS and a `rio_tiler.io.Reader.tile(...)` per tile. Zoom range
   comes from `_zoom_range` (min zoom fits the AOI in ~1 tile; max zoom matched to
   the raster's native resolution, capped at 18). A `_MAX_TILES=600` safety cap is
   logged (not silent) if hit. The HTML is `_maplibre_html`.
2. **Fallback (no geo stack)** — `_canvas_html` paints the change grid to an HTML
   `<canvas>` (loss/gain/stable colored cells), fully self-contained. This is what
   the offline mock-test env without rasterio produces.

Either way the emitted title contains "land-cover change" and the bundle has the
same shape (`{output_dir, html_path, tiles_path}`), so the handler and callers don't
branch on which path ran.

## Fan-out

**Single-task — no fan-out.** One render per change raster. The workflows order it
`after change`, the `DetectChange` step.

## Data & fields

- **Change codes → colors** (`_COLORS`): loss `-1` → `(215,48,39)` red, gain `+1` →
  `(26,152,80)` green; `0`/nodata render transparent (via the written mask).
- **`ChangeMap` returns:** `aoi_key`, `output_dir`, `html_path`, `tiles_path`.
- **Basemap:** CARTO Voyager raster (`a`–`d` subdomains expanded because MapLibre
  doesn't interpolate `{s}`), attribution "© OpenStreetMap © CARTO". Overridable via
  `basemap_url`.
- No filtering — it renders whatever change raster it's handed.

## External libraries / binaries

- **`rio-tiler`** (pip, `[geo]`; pulls `rasterio` + `morecantile`) — GeoTIFF write,
  Web-Mercator reprojection, XYZ tile slicing. **Optional**: absent → the canvas
  fallback (`try/except ImportError` in `_render_tiles`).
- **`numpy`** (core dep) — the RGB/mask array construction.
- **MapLibre GL JS 4.7.1** — loaded in the browser from `unpkg.com` by the emitted
  HTML (a runtime CDN dependency of the *page*, not a Python dep). The canvas
  fallback needs no JS libraries at all.
- No system binaries beyond what `rasterio` bundles (GDAL).

## Facets & workflows

| Facet | Kind | Effect / Cost | Purpose |
|---|---|---|---|
| `ChangeMap(change_path, aoi_key, title="Sentinel-2 land-cover change", basemap_url="") => (aoi_key, output_dir, html_path, tiles_path)` | event | io / cheap | Render the change raster as XYZ tiles + a MapLibre HTML viewer |

`Effect(kind="io")` (it writes an output bundle), `Cost(tier="cheap")`. No
`RetryPolicy` (no remote reads). Callers order it `after` the `DetectChange` step —
it reads that step's raster from the cache.

## Cache / output

- **Output bundle** at `output/s2/<aoi_key>/` (`storage.output_root()`):
  `index.html` (MapLibre viewer), `change.tif` (georeferenced RGBA GeoTIFF,
  downloadable), `tiles/{z}/{x}/{y}.png` (XYZ pyramid). This is **output**, not
  cache — no `.meta.json` sidecar here.
- On `FW_STORAGE=s3` the whole bundle goes to `s3://<bucket>/output/s2/…`, which the
  dashboard's `/output/raw` artifact server serves directly (so a fleet run is
  viewable from the Runs list). The COG + every tile stage to a local temp dir and
  finalize through `storage.write_bytes`.

## Gotchas & notes

- **The canvas fallback is a real, tested path** — the offline suite runs without
  rio-tiler and asserts `"canvas" in html`. Don't assume every rendered map is
  tiled; a runner missing the `[geo]` extra silently produces the canvas view.
- **Tile cap is logged, never silent** — hitting `_MAX_TILES=600` prints which zoom
  was dropped (`[map_render] tile cap …`). Raise it (and `FW_S2_MAX_SIZE`) for a
  large, high-zoom AOI.
- **GDAL needs a local file** — rasterio can't write/tile-read an S3 object in place,
  so the COG is written to a `TemporaryDirectory` and then republished through
  `storage`; keep local scratch available even on an S3 backend.

## Related specs

- [change-detection](change-detection.md) — produces the `change` raster this renders.
- [water-timeseries](water-timeseries.md) — the sibling renderer for the multi-year water viewer (reuses `map_render._BASEMAP` / `_zoom_range`).
- [cache-and-storage](cache-and-storage.md) — the `storage` backend the bundle is published through.
- [workflows](workflows.md) — the entry points that end in `ChangeMap`.
