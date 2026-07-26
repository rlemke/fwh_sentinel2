# Geocoding — place name → AOI bbox

**Namespace:** `s2.geo` ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (namespace `s2.geo`) ·
**Handlers:** `src/sentinel2/handlers/geo/geo_handlers.py` ·
**Tools:** `src/sentinel2/tools/_s2_tools/geocode.py` ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_geocode_resolve_mock`, `test_resolve_aoi_handler`)

## Overview

`s2.geo.ResolveAOI` is the front door for the by-name entry points: it turns a place
string ("Apuí, Amazonas, Brazil", "Great Salt Lake, Utah") into the
`min_lon,min_lat,max_lon,max_lat` bbox string the rest of the pipeline consumes,
using the OpenStreetMap Nominatim geocoder. It's the first step of `AnalyzeRegion`
and every water time-series workflow, so a user never has to hand-type a bbox.

## How it works

`geocode.resolve()` GETs `nominatim/search?q=<place>&format=json&limit=1`, takes the
top hit's `lat`/`lon`, and produces the bbox two ways:

- **`buffer_km > 0`** (default 10) — `_box_around(lat, lon, buffer_km)`: a box of that
  half-size centered on the place's point, using a cos-latitude longitude correction.
  This is the practical default because a municipality's full polygon can be enormous
  (Apuí ~54,000 km²), which would fan out into hundreds of scenes.
- **`buffer_km == 0`** — the geocoder's own `boundingbox` (`[south, north, west,
  east]`, reordered), for small places.

The mock path (`_resolve_mock`) is offline and deterministic: a stable point derived
from a SHA-256 of the name (roughly within Amazon lat/lon), so `AnalyzeRegion` runs
end-to-end with `use_mock=true` without network (`test_geocode_resolve_mock` asserts
determinism + that a bigger buffer yields a bigger box).

## Fan-out

**Single-task — no fan-out.** One geocoder lookup per run; it precedes and feeds the
downstream fan-out.

## Data & fields

- **Input:** `place` (non-empty; empty raises `ValueError`), `buffer_km`,
  `nominatim_url`.
- **Output:** `aoi` (the bbox string), `lat`, `lon`, `display_name`, `used_mock`.
- Bbox coordinates are rounded to 5 decimals. No filtering.

## External libraries / binaries

- **`requests`** (pip, `[geo]` extra) — the Nominatim HTTP lookup.
- **stdlib `math`** — the lat/lon box math; **`hashlib`** for the deterministic mock.
- No system binaries; no numpy/GDAL.

## Facets & workflows

| Facet | Kind | Effect / Cost | Purpose |
|---|---|---|---|
| `ResolveAOI(place, buffer_km=10.0, nominatim_url="https://nominatim.openstreetmap.org", use_mock=false) => (aoi, lat, lon, display_name, used_mock)` | event | external / cheap | Geocode a place name to an AOI bbox string |

Carries `with RetryPolicy()`, `Effect(kind="external")`, `Cost(tier="cheap")`.

## Cache / output

**No cache, no output artifact** — `ResolveAOI` is a stateless lookup returning a
string in its payload. (It is the one `s2.*` event facet that writes nothing to the
cache.)

## Gotchas & notes

- **Nominatim is keyless but rate-limited** (~1 req/s) and requires a descriptive
  `User-Agent` — both satisfied here (one lookup per run, a research UA string). Don't
  batch-hammer it.
- **`buffer_km` is the fan-out governor** — leaving it >0 keeps a run to a handful of
  scenes; `buffer_km=0` on a large admin area can explode the scene fan-out. For a
  lake, `buffer_km=0` fits the geocoder's lake bbox (better than an off-center buffer
  box that clips) — see the README's Okeechobee tuning note.
- **Non-ASCII place names** — Nominatim handles them, but note the framework's FFL
  literal handling prefers ASCII (a separate, framework-level caveat).

## Related specs

- [workflows](workflows.md) — `AnalyzeRegion` and all water time-series workflows start with `ResolveAOI`.
- [fan-out](fan-out.md) — why the `buffer_km` box (not the full polygon) is the default AOI.
- [gauges](gauges.md) — the resolved AOI is also what `ResolveLakeGauge` searches for a gauge.
