# Gauge & reservoir series — USGS / USBR

**Namespace:** `s2.level` ·
**FFL:** `src/sentinel2/ffl/sentinel2_landchange.ffl` (namespace `s2.level`) ·
**Handlers:** `src/sentinel2/handlers/level/level_handlers.py` ·
**Tools:** `src/sentinel2/tools/_s2_tools/level.py`, `s2_mocks.py` ·
**CLI:** `src/sentinel2/tools/{find_lake_gauge,lake_level,reservoir_storage,usbr_storage}.py` (+ `.sh` wrappers) ·
**Tests:** `tests/test_sentinel2_landchange.py` (`test_gauge_lookup_offline`, `test_lake_level_mock_and_overlay`, `test_reservoir_storage_mock`, `test_usbr_reservoir_mock`, `test_real_*_live`)

## Overview

`s2.level` supplies the **ground-truth** counterpart to satellite water *extent*: a
lake's surface *height* (level, ft) or *quantity* (storage, acre-feet) from a
physical gauge. A satellite sees footprint (km²); a gauge measures level/storage —
they track for a lake, but non-linearly (a flat pan bares hundreds of km² for a few
ft). Overlaying them (via [water-timeseries](water-timeseries.md)'s
`level_relative_path`) corroborates the satellite with an independent instrument.
Four facets cover three data sources: USGS NWIS level, USGS gauge discovery, USGS
reservoir storage, and USBR (Bureau of Reclamation) storage/elevation for the
Colorado-River giants USGS doesn't gauge.

## How it works

- **`FetchLakeLevel`** → `level.fetch_lake_level()`. GETs the USGS NWIS Daily Values
  service (`waterservices.usgs.gov/nwis/dv`, JSON), trying the requested param then
  the other elevation datums, picking the `timeSeries` with the most non-empty
  values. Caches the full series; the handler returns a compact summary.
- **`ResolveLakeGauge`** → `level.find_lake_gauge()`. So *any* US lake works by name:
  discovers `siteType=LK` gauges reporting any of the elevation params in the
  margin-expanded AOI bbox (USGS NWIS Site service, RDB/tab-delimited), then picks
  the gauge whose **station name best matches `place`** (token overlap after
  dropping generic stop-words like "lake"/"reservoir"/state codes), else the
  nearest. An explicit `site_id` short-circuits; raises when no USGS gauge exists.
- **`FetchReservoirStorage`** → `level.fetch_lake_storage()`. Same NWIS DV path but
  param `00054` (storage, acre-feet).
- **`FetchUSBRStorage`** → `level.fetch_usbr_reservoir()`. For a Reclamation
  reservoir USGS doesn't gauge — matched by substring (`"powell"`/`"mead"`): Lake
  Powell via the Upper-Colorado hydrodata CSV, Lake Mead via the RISE API CSV
  download; normalized to acre-feet ("ac-ft").

All four cache into one shared `lake-level` cache and return the **same doc shape**
(`relative_path`, `site_name`, `unit`, `point_count`, `min`, `max`), so
`WaterTimeSeriesMap` overlays any of them identically.

## Fan-out

**Single-task each — no fan-out.** One HTTP series fetch (or one gauge-discovery
query) per call. In the water time-series workflows these run as a single side
branch parallel to the per-year `ScanYears` fan-out.

## Data & fields

- **USGS param codes** (`level.ELEV_PARAMS`, preference order): `62614` (elevation
  above NGVD29, ft), `62615` (NAVD88, ft), `00062` (elevation, datum varies),
  `00065` (gage height, ft — a *relative* stage, used last, only with `siteType=LK`).
  `STORAGE_PARAM = "00054"` (acre-feet).
- **Defaults:** `GREAT_SALT_LAKE = "10010000"` at Saltair Boat Harbor (south arm),
  `ELEV_PARAM = "62614"`.
- **USBR registry** (`USBR_RESERVOIRS`): `powell` → UC hydrodata site 919
  (storage datatype 17 / elevation 49); `mead` → RISE item 6124 (storage) / 6123
  (elevation). `_USBR_UNIT` = storage "ac-ft" / elevation "ft".
- **Gauge-discovery output:** `site_id`, `param`, `site_name`, `lat`, `lon`,
  `distance_km`, `confident` (bool — false = nearest-fallback with no name match),
  `candidate_count`, `source`.
- **Parsing:** `_parse_rdb` handles USGS RDB (comment lines, header row, a format-spec
  row, then data); `_series_points` drops empty/`-999999` values.

## External libraries / binaries

- **`requests`** (pip, `[geo]` extra) — every USGS NWIS + USBR HTTP call.
- **stdlib only otherwise** — `csv`/`io` (RISE CSV), `math` (haversine), `re`
  (name-token split), `datetime` (`decimal_year`). No GDAL, no numpy here.
- The mock path (`s2_mocks.mock_lake_level` / `mock_reservoir_storage`) is fully
  offline and deterministic (a V-shaped drought trough + jitter).

## Facets & workflows

| Facet | Kind | Effect / Cost | Purpose |
|---|---|---|---|
| `FetchLakeLevel(site_id="10010000", date_from, date_to, param="62614", use_mock=false) => (relative_path, site_name, unit, point_count, min, max)` | event | external / cheap | Daily lake-surface elevation from USGS NWIS (US only) |
| `ResolveLakeGauge(aoi, place="", site_id="", margin_deg=0.1, params="", use_mock=false) => (site_id, param, site_name, lat, lon, distance_km, confident, candidate_count, source)` | event | external / cheap | Auto-discover the best USGS lake gauge for an AOI by name |
| `FetchReservoirStorage(site_id, date_from, date_to, use_mock=false) => (relative_path, site_name, unit, point_count, min, max)` | event | external / cheap | Daily USGS reservoir storage (param 00054, acre-feet) |
| `FetchUSBRStorage(reservoir, date_from, date_to, metric="storage", use_mock=false) => (relative_path, site_name, unit, point_count, min, max)` | event | external / cheap | Reclamation reservoir storage/elevation (Powell/Mead) |

All four carry `with RetryPolicy()` and `Effect(kind="external")`, `Cost(tier="cheap")`.

## Cache / output

- **Cache type `lake-level`** — a JSON series document under
  `$FW_CACHE_ROOT/s2/lake-level/<site_id>/<param>/<date_from>_<date_to>.json`
  (USBR: `usbr-<key>/<metric>/…`), with a `.meta.json` sidecar. The renderer reads it
  by `relative_path` via `level.load_series()`.
- No standalone output artifact — the series is consumed by
  [water-timeseries](water-timeseries.md). Local or S3/MinIO per `FW_STORAGE`.

## Gotchas & notes

- **US gauges only** — NWIS is a US service; a non-US lake has no gauge here and the
  overlay must be dropped.
- **Name the lake, not a feature in it** — auto-discovery matches on the place name,
  so `"Great Salt Lake"` (confident) beats `"Antelope Island"` (nearest-fallback,
  `confident=false`). The handler logs a WARNING on a low-confidence match.
- **Reclamation reservoirs aren't in USGS** — Lake Mead/Powell have no NWIS elevation
  gauge (`ResolveLakeGauge` raises with a clear message) and don't report `00054`;
  use `FetchUSBRStorage` (or the `ReservoirStorageUSBR` workflow) for those.
- **A gauge is one point, the AOI is an area** — e.g. the Great Salt Lake south-arm
  gauge vs a causeway-split two-arm AOI; expect the joint drought minimum + trend to
  carry the signal, not a perfect area↔height fit.
- **Shipped CLIs** — `find_lake_gauge`, `lake_level`, `reservoir_storage`,
  `usbr_storage` are the shipped reference CLIs over these same functions
  (`tools/README.md`).

## Related specs

- [water-timeseries](water-timeseries.md) — overlays these series on satellite water extent.
- [geocoding](geocoding.md) — resolves the place name into the AOI bbox gauge discovery searches.
- [workflows](workflows.md) — `WaterLevelTimeSeries` / `WaterStorageTimeSeries` / `ReservoirStorageUSBR` compose these.
- [cache-and-storage](cache-and-storage.md) — the `lake-level` JSON cache + sidecar.
