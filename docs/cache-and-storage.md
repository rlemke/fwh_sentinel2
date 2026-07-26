# Cache & storage — content-addressed sidecar cache

**Namespace:** cross-cutting (`s2` cache namespace) ·
**FFL:** n/a — infrastructure under every `s2.*` facet ·
**Tools:** `src/sentinel2/tools/_s2_tools/{storage,sidecar}.py` ·
**Contract:** `agent-spec/cache-layout.agent-spec.yaml`, `agent-spec/tools-pattern.agent-spec.yaml` ·
**Tests:** `tests/test_sentinel2_landchange.py` (`tools_env` fixture drives all I/O through a tmp `FW_CACHE_ROOT`/`FW_DATA_ROOT`; `test_mock_chain_end_to_end` asserts `was_cached`)

## Overview

This is the storage substrate the whole package rides on: one backend abstraction
(local disk **or** S3/MinIO) and one per-entry sidecar cache protocol, shared verbatim
by the CLI tools and the FFL handlers so the terminal and the runtime read/write the
same cache. It's what makes re-runs cheap (content-addressed artifacts + idempotent
cache hits) and what lets a fleet run render straight to MinIO with no shared disk.

## How it works

**`storage.py` — backend, dispatched on the path.** `backend()` reads `FW_STORAGE`
(`local` default or `s3`). Every op (`exists`/`read_bytes`/`write_bytes`/`read_text`/
`write_text`/`list_files`) checks `is_s3(path)` and either hits the filesystem or a
`boto3` S3 client (`_s3()`, configured from `FW_S3_ENDPOINT`/`FW_S3_REGION`/
`FW_S3_*`/`AWS_*`). Local writes are **atomic**: write `<path>.tmp`, `fsync`,
`os.replace`. Roots: `data_root()` (`FW_DATA_ROOT`, else `~/afl_data` local or
`s3://afl-cache`), `cache_root()` (`FW_CACHE_ROOT`, else `<data_root>/cache`),
`output_root()` (see below). `join()` is S3-aware (URI-style joins for `s3://`).

**`sidecar.py` — per-entry cache protocol.** `cache_path(cache_type, rel)` resolves
`<cache_root>/s2/<cache_type>/<rel>`. `write(...)` stores the artifact **and** a
sibling `<path>.meta.json` recording `version`, `cache_type`, `relative_path`,
`size_bytes`, `sha256`, `source`, `tool`, `created_at`, and `extras` (e.g. array
shape/dtype). `exists()` requires **both** the artifact and its sidecar present.
`list_entries(cache_type)` lists artifacts (sidecars excluded). Because every key gets
its own sidecar, N writers on N keys never contend — the design point in
`cache-layout.agent-spec.yaml` (per-entry sidecars replace a shared `manifest.json` +
lock).

## Fan-out

**n/a — infrastructure.** But it is precisely what makes fan-out safe: the per-scene
fan-out ([fan-out](fan-out.md)) writes N distinct `scene-index/<aoi_key>/<index>/<scene>.npz`
keys concurrently across runners, and the sidecar-per-key protocol means those writes
never lock against each other. Content is exchanged through this shared cache, not the
step payload.

## Data & fields

- **Namespace:** `storage.NAMESPACE = "s2"` — every cache path is
  `<cache_root>/s2/<cache_type>/…`.
- **Cache types** (the `<cache_type>` segment): `scene-index`, `composite`, `change`
  (all `.npz`, from [source-adapters](source-adapters.md) / [change-detection](change-detection.md)),
  `lake-level` (`.json`, from [gauges](gauges.md)).
- **Sidecar suffix:** `.meta.json`; fields listed above. `sha256` is the content
  address; `source`/`tool` give lineage (e.g. `tool="fetch_scene_index"`,
  `source="median of 5 scenes"`).
- **Output roots:** the rendered map bundles (not cache) go to `output_root()` —
  `output/s2/…` and `output/s2-timeseries/…`.

## External libraries / binaries

- **`boto3`** (pip, `[s3]` extra) — imported lazily only when a path is `s3://`; the
  local backend needs nothing beyond stdlib.
- **stdlib** — `os`, `hashlib` (sha256), `json`, `datetime`. No numpy/GDAL here.

## Facets & workflows

**None** — this feature registers no facet. It is the library layer under every
`s2.*` handler. The handler-side shim `handlers/shared/s2_utils.py` re-exports these
modules (via a `sys.path` insert of `tools/`) so a handler running in the runtime and
a CLI running standalone resolve the same `_s2_tools` and the same cache.

## Cache / output

- **Cache:** `$FW_CACHE_ROOT/s2/<cache_type>/<rel>` + `<rel>.meta.json` sidecar.
- **Output:** `output/s2/<aoi_key>/` (change map) and `output/s2-timeseries/<aoi_key>/`
  (water viewer).
- **S3 layout** (`FW_STORAGE=s3`): cache at `s3://<bucket>/cache/s2/…`, bundle at
  `s3://<bucket>/output/s2/…` — the latter served by the dashboard's `/output/raw`
  artifact server (point it with `FW_S2_OUTPUT_BASE`/`FW_S3_OUTPUT_BASE`).

## Gotchas & notes

- **`output_root()` treats `FW_OUTPUT_BASE` differently per backend.** On `s3` it's
  honored **only if itself an `s3://` URI** (it's often a *local* scratch dir under the
  runtime's staging model) — otherwise output lands at `<data_root>/output`. On
  `local` it's used as-is. This is why a fleet run renders to MinIO even when
  `FW_OUTPUT_BASE` points at local scratch.
- **A cache hit needs both files** — an artifact without its `.meta.json` reads as a
  miss (and would be re-fetched); don't hand-delete sidecars.
- **GDAL/rasterio can't write S3 in place** — the tile renderers stage the COG + tiles
  in a `TemporaryDirectory` and finalize through `storage.write_bytes`; keep local
  scratch available even on an S3 backend (see [change-map](change-map.md)).
- **Content addressing = cheap re-runs** — the sha256 sidecar + deterministic cache
  keys (`aoi_key` + index + window + scene id) mean changing a threshold/method reuses
  every fetched scene; only the cheap reduce/render re-runs.

## Related specs

- [source-adapters](source-adapters.md), [change-detection](change-detection.md),
  [gauges](gauges.md) — the features that write the cache types.
- [change-map](change-map.md), [water-timeseries](water-timeseries.md) — write output
  bundles through this backend (incl. S3/MinIO).
- [fan-out](fan-out.md) — why the per-entry sidecar (no shared lock) matters under
  concurrent writes.
