# FFL Examples — `sentinel2-landchange`

Every numbered scenario is a **complete, compilable FFL file**. Copy one into
`my.ffl` and run it:

```bash
fw ffl run --primary my.ffl \
  --library ~/fw_handlers/fwh_sentinel2/src/sentinel2/ffl/sentinel2_landchange.ffl \
  --workflow my.s2.<WorkflowName>
```

A runner serving the `s2` namespace must be up
(`fw runner start --domain sentinel2-landchange`). Every block below is
compile-checked against the domain's FFL. Add `use_mock = true` to any of them to
exercise the pipeline offline with synthetic rasters.

New to the language? Start with the
[FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md)
and the [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical).

---

## The building blocks

This is the richest FFL in the fleet — a custom mixin, schemas, a reusable fan-out
workflow, and multi-stage composition. Signatures are abridged; the FFL source is
authoritative.

| Declaration | Role |
|---|---|
| `s2.mixins.RetryPolicy(max_retries = 4, backoff_ms = 2000)` | A **custom mixin** — declared once, attached to every network facet |
| `s2.source.SearchScenes(aoi, date_from, date_to, max_cloud, …) => (count, scene_ids: Json)` | STAC search → a Json list of scene ids |
| `s2.source.FetchSceneIndex(scene_id, aoi, index, …) => (relative_path, …)` | One scene → one cached index raster |
| `s2.scan.ScanScenes(scene_ids: Json, aoi, index, …) => (count)` | **Reusable fan-out workflow**: `FetchSceneIndex` per scene |
| `s2.analyze.Composite(aoi, date_from, date_to, scene_ids, index, reducer, …)` | Cloud-robust median composite over the cached scenes |
| `s2.analyze.DetectChange(baseline_path, recent_path, aoi_key, method, threshold, …)` | Baseline vs recent → change raster + stats |
| `s2.render.ChangeMap(change_path, aoi_key, title, …)` | Tiles + MapLibre viewer |
| `s2.workflows.AnalyzeAOI(...)` / `AnalyzeRegion(place, …)` | The shipped end-to-end pipelines |
| `s2.workflows.WaterTimeSeries` / `WaterLevelTimeSeries` / … | Multi-year water families |

---

## 1. Run what ships — no FFL to write

```bash
fw ffl seed --include sentinel2-landchange

# a bounding box
fw ffl run --workflow s2.workflows.AnalyzeAOI \
  --inputs '{"aoi": "-122.55,37.70,-122.35,37.85", "index": "ndvi"}'

# or a named place (geocoded to a bbox first)
fw ffl run --workflow s2.workflows.AnalyzeRegion \
  --inputs '{"place": "Apui, Amazonas, Brazil", "buffer_km": 10.0}'
```

Write FFL when you want a different *shape* — your own epochs, a different index,
extra error handling, or a pipeline that stops after the composite.

## 2. The smallest useful workflow — search → fan out → composite

Three steps, and the whole distributed shape is visible: a search that returns a
list, a fan-out workflow over that list, and a fan-in composite ordered with
`after`.

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
            aoi = $.aoi,
            date_from = $.date_from,
            date_to = $.date_to,
            scene_ids = search.scene_ids,
            index = "ndvi",
            reducer = "median"
            ) after scan

        yield OneComposite(path = comp.relative_path, scenes = comp.scene_count)
    }
}
```

Rules visible above: `=>` sits on the **same line** as the closing `)`; references
are always `step.field`; `$.aoi` reads the workflow's parameter.

## 3. Two epochs in parallel, then compare

Nothing links the baseline branch to the recent branch, so the runtime runs both
at once — two searches, two fan-outs, two composites — and only `change` waits for
both, because it references both.

```ffl
namespace my.s2 {

    use s2.source
    use s2.scan
    use s2.analyze
    use s2.render

    /** Baseline vs recent land-cover change for one AOI. */
    workflow MyChangeMap(aoi: String = "-122.55,37.70,-122.35,37.85",
        baseline_from: String = "2018-06-01", baseline_to: String = "2018-09-30",
        recent_from: String = "2024-06-01", recent_to: String = "2024-09-30") => (html_path: String, pct_loss: Double) andThen {

        base_search = s2.source.SearchScenes(aoi = $.aoi, date_from = $.baseline_from, date_to = $.baseline_to)
        base_scan = s2.scan.ScanScenes(scene_ids = base_search.scene_ids, aoi = $.aoi, index = "ndvi")
        base = s2.analyze.Composite(
            aoi = $.aoi, date_from = $.baseline_from, date_to = $.baseline_to,
            scene_ids = base_search.scene_ids, index = "ndvi"
            ) after base_scan

        recent_search = s2.source.SearchScenes(aoi = $.aoi, date_from = $.recent_from, date_to = $.recent_to)
        recent_scan = s2.scan.ScanScenes(scene_ids = recent_search.scene_ids, aoi = $.aoi, index = "ndvi")
        recent = s2.analyze.Composite(
            aoi = $.aoi, date_from = $.recent_from, date_to = $.recent_to,
            scene_ids = recent_search.scene_ids, index = "ndvi"
            ) after recent_scan

        change = s2.analyze.DetectChange(
            baseline_path = base.relative_path,
            recent_path = recent.relative_path,
            aoi_key = recent.aoi_key,
            method = "difference",
            threshold = 0.15)

        map = s2.render.ChangeMap(
            change_path = change.relative_path,
            aoi_key = change.aoi_key,
            title = "NDVI change"
            ) after change

        yield MyChangeMap(html_path = map.html_path, pct_loss = change.pct_loss)
    }
}
```

This is `AnalyzeAOI` written out longhand — read the shipped one for the full
version with all its knobs.

## 4. Fan out directly over a scene list

`ScanScenes` is itself a workflow whose body is a `foreach`. You can write your own
when you want a different per-scene step:

```ffl
namespace my.s2 {

    use s2.source

    /** One FetchSceneIndex task per scene id — parallel across the fleet. */
    workflow MyScan(scene_ids: Json, aoi: String, index: String = "ndvi") => (count: Long) andThen foreach sid in $.scene_ids {

        idx = s2.source.FetchSceneIndex(scene_id = $.sid, aoi = $.aoi, index = $.index)

        yield MyScan(count = 1)
    }
}
```

Because the `foreach` hangs off the **workflow**, the loop variable and the
workflow's parameters share one `$` (`$.sid`, `$.aoi`). When a `foreach` hangs off
a *step* instead, use `$$` to reach the workflow — see the `when` example below.

## 5. Reuse the shipped workflows

Workflows compose like facets. `AnalyzeRegion` does exactly this: geocode, then
call `AnalyzeAOI`.

```ffl
namespace my.s2 {

    use s2.workflows

    /** Wrap the shipped pipeline and reshape its result. */
    workflow RegionHeadline(place: String = "Apui, Amazonas, Brazil") => (headline: String, html_path: String) andThen {

        run = s2.workflows.AnalyzeRegion(place = $.place, buffer_km = 10.0, method = "classify")

        yield RegionHeadline(
            headline = run.status ++ ": " ++ run.detail,
            html_path = run.html_path)
    }
}
```

## 6. Sweep many years — nested fan-out

`ScanYears` fans `WaterYear` out over a list of years, and `WaterYear` itself fans
`FetchSceneIndex` out over that year's scenes. Fan-out nests without any special
syntax.

```ffl
namespace my.s2 {

    use s2.workflows

    /** One water composite per year, all years in parallel. */
    workflow MyWaterYears(aoi: String, years: Json) => (count: Long) andThen {

        scanned = s2.workflows.ScanYears(
            aoi = $.aoi,
            years = $.years,
            index = "ndwi",
            max_cloud = 15.0)

        yield MyWaterYears(count = scanned.count)
    }
}
```

```bash
fw ffl run --primary my.ffl --library …/sentinel2_landchange.ffl --workflow my.s2.MyWaterYears \
  --inputs '{"aoi": "-112.6,40.6,-111.9,41.4", "years": ["2019","2020","2021","2022"]}'
```

## 7. Call-time mixins — including this domain's own

`RetryPolicy` is declared in `s2.mixins` and attached to every network facet in its
declaration. At a **call site** you can add or override any mixin for one
particular use:

```ffl
namespace my.s2 {

    use s2.source
    use s2.mixins

    /** A flaky STAC endpoint: more retries here, longer timeout. */
    workflow StubbornSearch(aoi: String, date_from: String, date_to: String) => (scenes: Int) andThen {

        search = s2.source.SearchScenes(
            aoi = $.aoi, date_from = $.date_from, date_to = $.date_to) with RetryPolicy(max_retries = 8, backoff_ms = 5000) with Timeout(minutes = 30)

        yield StubbornSearch(scenes = search.count)
    }
}
```

## 8. Survive a bad epoch — `catch`

`catch` runs when its step errors after retries are exhausted.

```ffl
namespace my.s2 {

    use s2.source
    use s2.scan

    /** If the search fails, end with a partial result instead of an error. */
    workflow BestEffortScan(aoi: String, date_from: String, date_to: String) => (status: String, count: Long) andThen {

        search = s2.source.SearchScenes(
            aoi = $.aoi, date_from = $.date_from, date_to = $.date_to) catch {
            yield BestEffortScan(status = "stac_search_failed", count = 0)
        }

        scan = s2.scan.ScanScenes(scene_ids = search.scene_ids, aoi = $.aoi, index = "ndvi")

        yield BestEffortScan(status = "completed", count = scan.count)
    }
}
```

## 9. Branch on a result — `when`

A `when` block hangs off the step it inspects: inside a case `$` is that step and
`$$` reaches the workflow's parameters. Every `when` needs a default case, last.

```ffl
namespace my.s2 {

    use s2.source
    use s2.scan

    /** Don't burn COG reads on an epoch with too few cloud-free scenes. */
    workflow GuardedEpoch(aoi: String, date_from: String, date_to: String, min_scenes: Int = 3) => (status: String, count: Long) andThen {

        search = s2.source.SearchScenes(
            aoi = $.aoi, date_from = $.date_from, date_to = $.date_to) andThen when {
            case $.count >= $$.min_scenes => {
                scan = s2.scan.ScanScenes(scene_ids = $.scene_ids, aoi = $$.aoi, index = "ndvi")
                yield GuardedEpoch(status = "scanned", count = scan.count)
            }
            case _ => {
                yield GuardedEpoch(status = "too_cloudy", count = 0)
            }
        }
    }
}
```

---

## Cheat sheet

| You want to… | Write |
|---|---|
| Read a workflow/step parameter | `$.name` (`$$.name` one level out) |
| Read a previous step's result | `stepname.field` |
| Run steps in parallel | write them with no reference between them |
| Order steps that share only a cache | `step = Facet(…) after other` |
| Fan out over a list | `workflow W(items: Json) … andThen foreach i in $.items { … }` |
| Reuse a fan-out | call the fan-out **workflow** as a step (`s2.scan.ScanScenes`) |
| Override a mixin for one call | `… with RetryPolicy(max_retries = 8) with Timeout(minutes = 30)` |
| Handle a step failure | `step = Facet(…) catch { yield … }` |
| Branch | `step = Facet(…) andThen when { case <bool> => { … } case _ => { … } }` |
| Run offline | pass `use_mock = true` |

**Validate before you run:** `afl my.ffl --check` or MCP `fw_validate`. Every error
carries a `rule_id` — fetch `fw://docs/rules/{rule_id}` for a wrong/right pair.

## See also

- [`docs/README.md`](README.md) — per-feature specs for this domain
- [FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md) ·
  [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical) ·
  [relative `$`-scoping](https://github.com/rlemke/facetwork/blob/main/docs/architecture/ffl-relative-scoping.md)
- The domain's FFL under `src/sentinel2/ffl/` — the source of truth for every signature above
