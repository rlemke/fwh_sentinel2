"""Tests for the fwh_sentinel2 package.

Covers: (1) the FFL parses + validates + compiles and exposes the expected
workflows/facets; (2) the offline mock chain (search -> per-scene index ->
composite x2 -> change -> render) runs end-to-end with coherent stats + an HTML
map; (3) the classify method's land-cover transitions; (4) handler dispatch.

All cache/output writes go to a tmp dir via AFL_CACHE_ROOT/AFL_DATA_ROOT, so the
default suite needs no network, GDAL, or external storage. A live STAC test is
opt-in (S2_LIVE=1).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
import sentinel2

_PKG = Path(sentinel2.__file__).resolve().parent
_FFL = _PKG / "ffl" / "sentinel2_landchange.ffl"
_TOOLS = _PKG / "tools"


# ── FFL compilation ───────────────────────────────────────────────────────────


def _compile() -> dict:
    from facetwork.emitter import emit_dict
    from facetwork.parser import FFLParser
    from facetwork.source import CompilerInput, FileOrigin, SourceEntry
    from facetwork.validator import validate

    entry = SourceEntry(text=_FFL.read_text(), origin=FileOrigin(path=str(_FFL)), is_library=False)
    program_ast, _registry = FFLParser().parse_sources(CompilerInput(primary_sources=[entry]))
    result = validate(program_ast)
    assert not result.errors, "; ".join(str(e) for e in result.errors)
    return emit_dict(program_ast, include_locations=False)


def test_ffl_compiles_and_validates():
    assert _compile()


def test_ffl_defines_expected_workflows_and_facets():
    text = _FFL.read_text()
    for name in ["AnalyzeAOI", "AnalyzeRegion", "ResolveAOI", "ScanScenes", "SearchScenes",
                 "FetchSceneIndex", "Composite", "DetectChange", "ChangeMap"]:
        assert name in text, f"missing declaration {name}"


def test_geocode_resolve_mock(tools_env):
    from _s2_tools import geocode, stac

    res = geocode.resolve("Apuí, Amazonas, Brazil", buffer_km=10.0, use_mock=True)
    assert res["used_mock"] is True and res["display_name"]
    # the resolved aoi must be a valid bbox the rest of the pipeline can parse
    w, s, e, n = stac.parse_bbox(res["aoi"])
    assert w < e and s < n
    # deterministic
    assert geocode.resolve("Apuí, Amazonas, Brazil", buffer_km=10.0, use_mock=True)["aoi"] == res["aoi"]
    # bigger buffer -> bigger box
    big = geocode.resolve("Apuí, Amazonas, Brazil", buffer_km=40.0, use_mock=True)
    bw, bs, be, bn = stac.parse_bbox(big["aoi"])
    assert (be - bw) > (e - w)


def test_resolve_aoi_handler(tools_env):
    from sentinel2.handlers.geo.geo_handlers import handle_resolve_aoi
    from _s2_tools import stac

    res = handle_resolve_aoi({"place": "Novo Progresso", "buffer_km": 8.0, "use_mock": True})
    assert res["aoi"] and stac.parse_bbox(res["aoi"])


# ── offline mock chain through _s2_tools ───────────────────────────────────────


@pytest.fixture
def tools_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AFL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AFL_CACHE_ROOT", str(tmp_path / "cache"))
    monkeypatch.setenv("AFL_OUTPUT_BASE", str(tmp_path / "output"))
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    for mod in [m for m in sys.modules if m == "_s2_tools" or m.startswith("_s2_tools.")]:
        del sys.modules[mod]
    return importlib.import_module("_s2_tools")


def test_mock_chain_end_to_end(tools_env):
    from _s2_tools import map_render, raster, stac

    aoi = "-122.55,37.70,-122.35,37.85"
    base_scenes = stac.search(aoi, "2018-06-01", "2018-09-30", use_mock=True)
    assert base_scenes
    for s in base_scenes:
        raster.fetch_scene_index(s["scene_id"], aoi, index="ndvi", use_mock=True)
    base_ids = [s["scene_id"] for s in base_scenes]
    base = raster.composite(aoi, "2018-06-01", "2018-09-30", scene_ids=base_ids,
                            index="ndvi", use_mock=True)
    assert base["scene_count"] == len(base_scenes)

    again = raster.fetch_scene_index(base_scenes[0]["scene_id"], aoi, index="ndvi", use_mock=True)
    assert again["was_cached"] is True

    recent_scenes = stac.search(aoi, "2024-06-01", "2024-09-30", use_mock=True)
    for s in recent_scenes:
        raster.fetch_scene_index(s["scene_id"], aoi, index="ndvi", use_mock=True)
    recent = raster.composite(aoi, "2024-06-01", "2024-09-30",
                              scene_ids=[s["scene_id"] for s in recent_scenes],
                              index="ndvi", use_mock=True)

    change = raster.detect_change(base["relative_path"], recent["relative_path"],
                                  base["aoi_key"], method="difference", threshold=0.15, use_mock=True)
    assert change["total_pixels"] == 16 * 16
    assert change["changed_pixels"] == change["class_counts"]["loss"] + change["class_counts"]["gain"]
    assert 0.0 <= change["pct_loss"] <= 100.0

    bundle = map_render.render_change_map(change["relative_path"], change["aoi_key"], detail="test")
    html = Path(bundle["html_path"]).read_text()
    assert "land-cover change" in html

    try:
        import morecantile  # noqa: F401
        import rasterio  # noqa: F401
        import rio_tiler  # noqa: F401
        has_geo = True
    except ImportError:
        has_geo = False
    tiles = list(Path(bundle["tiles_path"]).rglob("*.png"))
    if has_geo:
        assert "maplibre" in html.lower(), "expected a MapLibre tiled viewer"
        assert tiles, "expected an XYZ tile pyramid"
        assert Path(bundle["output_dir"], "change.tif").is_file(), "expected the georeferenced COG"
    else:
        assert "canvas" in html.lower()


def test_classify_change_method(tools_env):
    from _s2_tools import raster, stac

    aoi = "-122.55,37.70,-122.35,37.85"
    ids = {}
    for win in (("2018-06-01", "2018-09-30"), ("2024-06-01", "2024-09-30")):
        scenes = stac.search(aoi, *win, use_mock=True)
        ids[win[0]] = [s["scene_id"] for s in scenes]
        for s in scenes:
            raster.fetch_scene_index(s["scene_id"], aoi, index="ndvi", use_mock=True)
    base = raster.composite(aoi, "2018-06-01", "2018-09-30", scene_ids=ids["2018-06-01"],
                            index="ndvi", use_mock=True)
    recent = raster.composite(aoi, "2024-06-01", "2024-09-30", scene_ids=ids["2024-06-01"],
                              index="ndvi", use_mock=True)

    ch = raster.detect_change(base["relative_path"], recent["relative_path"], base["aoi_key"],
                              method="classify", use_mock=True)
    assert ch["method"] == "classify"
    assert ch["changed_pixels"] > 0 and ch["pct_loss"] > 0
    cc = ch["class_counts"]
    assert set(cc) >= {"loss", "gain", "stable", "baseline", "recent", "transitions"}
    assert set(cc["baseline"]) == {"water", "built_bare", "sparse_veg", "dense_veg"}
    assert sum(cc["baseline"].values()) == ch["total_pixels"]
    assert all("->" in k and k.split("->")[0] != k.split("->")[1] for k in cc["transitions"])
    assert sum(cc["transitions"].values()) == ch["changed_pixels"]


def test_water_change_method(tools_env):
    from _s2_tools import raster, stac

    aoi = "-112.50,41.00,-112.30,41.20"
    ids = {}
    for win in (("2019-07-01", "2019-09-30"), ("2024-07-01", "2024-09-30")):
        scenes = stac.search(aoi, *win, use_mock=True)
        ids[win[0]] = [s["scene_id"] for s in scenes]
        for s in scenes:
            raster.fetch_scene_index(s["scene_id"], aoi, index="ndwi", use_mock=True)
    base = raster.composite(aoi, "2019-07-01", "2019-09-30", scene_ids=ids["2019-07-01"],
                            index="ndwi", use_mock=True)
    recent = raster.composite(aoi, "2024-07-01", "2024-09-30", scene_ids=ids["2024-07-01"],
                              index="ndwi", use_mock=True)
    ch = raster.detect_change(base["relative_path"], recent["relative_path"], base["aoi_key"],
                              method="water", threshold=0.0, use_mock=True)
    assert ch["method"] == "water"
    cc = ch["class_counts"]
    assert {"baseline_water", "recent_water", "water_change_pct"} <= set(cc)
    assert isinstance(cc["water_change_pct"], (int, float))
    # loss = pixels that went water -> land (receded)
    assert ch["changed_pixels"] == cc["loss"] + cc["gain"]


def test_water_timeseries(tools_env):
    from _s2_tools import raster, stac, timeseries

    aoi = "-112.50,41.00,-112.30,41.20"
    years = ["2018", "2020", "2022"]
    for yr in years:
        win = (f"{yr}-07-01", f"{yr}-09-30")
        scenes = stac.search(aoi, *win, use_mock=True)
        for s in scenes:
            raster.fetch_scene_index(s["scene_id"], aoi, index="ndwi", use_mock=True)
        raster.composite(aoi, *win, scene_ids=[s["scene_id"] for s in scenes],
                         index="ndwi", use_mock=True)

    bundle = timeseries.render_water_timeseries(aoi, index="ndwi", water_threshold=0.0)
    assert bundle["year_count"] == 3
    html = Path(bundle["html_path"]).read_text()
    for yr in years:                       # year tab bar + chart labels
        assert yr in html
    assert "maplibre-gl" in html and "chart.js" in html.lower()
    # geo stack present in CI -> per-year tile pyramids
    try:
        import rio_tiler  # noqa: F401
        tiles = list(Path(bundle["output_dir"], "tiles").rglob("*.png"))
        assert tiles and any(f"/tiles/2022/" in str(t) for t in tiles)
    except ImportError:
        pass


def test_lake_level_mock_and_overlay(tools_env):
    """Mock USGS level series caches + round-trips, and the time-series renderer
    overlays it (dual-axis chart) on the per-year water extent."""
    from _s2_tools import level, raster, stac, timeseries

    lv = level.fetch_lake_level("10010000", "2018-01-01", "2022-12-31", use_mock=True)
    assert lv["unit"] == "ft" and lv["point_count"] > 0
    assert lv["series"][0]["value"] > 4000  # plausible GSL elevation
    # cache round-trip via the relative_path the renderer uses
    again = level.load_series(lv["relative_path"])
    assert again["point_count"] == lv["point_count"]

    aoi = "-112.50,41.00,-112.30,41.20"
    years = ["2018", "2020", "2022"]
    for yr in years:
        win = (f"{yr}-07-01", f"{yr}-09-30")
        scenes = stac.search(aoi, *win, use_mock=True)
        for s in scenes:
            raster.fetch_scene_index(s["scene_id"], aoi, index="ndwi", use_mock=True)
        raster.composite(aoi, *win, scene_ids=[s["scene_id"] for s in scenes],
                         index="ndwi", use_mock=True)

    bundle = timeseries.render_water_timeseries(aoi, index="ndwi", water_threshold=0.0, level=lv)
    assert bundle["has_level"] is True
    html = Path(bundle["html_path"]).read_text()
    assert '"level":' in html and '"line":' in html        # level embedded
    assert "yAxisID:'yL'" in html and "yAxisID:'yR'" in html  # dual axis

    # handler dispatch for the level facet
    from sentinel2.handlers.level.level_handlers import handle_fetch_lake_level
    hr = handle_fetch_lake_level({"site_id": "10010000", "date_from": "2018-01-01",
                                  "date_to": "2019-12-31", "use_mock": True})
    assert hr["point_count"] > 0 and hr["relative_path"]


def test_gauge_lookup_offline(tools_env):
    """RDB parsing + name-preference scoring + mock/override, no network."""
    from _s2_tools import level

    # RDB parse: comment lines, header, format row, then data.
    rdb = ("# comment\nagency_cd\tsite_no\tstation_nm\tsite_tp_cd\tdec_lat_va\tdec_long_va\n"
           "5s\t15s\t30s\t5s\t16s\t16s\n"
           "USGS\t09379900\tLAKE POWELL AT GLEN CANYON DAM, AZ\tLK\t36.9366\t-111.4840\n"
           "USGS\t10336710\tMARLETTE LAKE NR CARSON CITY, NV\tLK\t39.1729\t-119.9055\n")
    rows = level._parse_rdb(rdb)
    assert len(rows) == 2 and rows[0]["site_no"] == "09379900"

    # name-token matching drops generic words ("lake") and matches the rare one.
    assert "powell" in level._tokens("Lake Powell")
    assert "lake" not in level._tokens("Lake Powell")

    # explicit override + mock paths (no network).
    ov = level.find_lake_gauge("-112,40,-111,41", site_id="10010000")
    assert ov["site_id"] == "10010000" and ov["source"] == "explicit"
    mk = level.find_lake_gauge("-112,40,-111,41", place="Great Salt Lake", use_mock=True)
    assert mk["site_id"] == level.GREAT_SALT_LAKE and mk["confident"] is True


@pytest.mark.skipif(os.environ.get("S2_LIVE") != "1",
                    reason="live USGS test; set S2_LIVE=1 to run (hits the network)")
def test_real_lake_level_live(tools_env):
    """Live USGS NWIS daily elevation for the Great Salt Lake gauge."""
    from _s2_tools import level

    lv = level.fetch_lake_level("10010000", "2020-01-01", "2022-12-31", use_mock=False)
    assert lv["point_count"] > 300 and lv["unit"] == "ft"
    assert 4180 < lv["min"] < lv["max"] < 4220  # GSL elevation band, ft NGVD29


@pytest.mark.skipif(os.environ.get("S2_LIVE") != "1",
                    reason="live USGS test; set S2_LIVE=1 to run (hits the network)")
def test_real_gauge_lookup_live(tools_env):
    """Live gauge discovery: a named lake resolves to its USGS elevation gauge."""
    from _s2_tools import level

    g = level.find_lake_gauge("-111.7,36.85,-110.8,37.55", place="Lake Powell")
    assert g["site_id"] == "09379900" and g["confident"] is True
    # a Reclamation reservoir with no USGS elevation gauge raises clearly.
    with pytest.raises(ValueError, match="no USGS lake-elevation gauge"):
        level.find_lake_gauge("-114.95,35.9,-114.3,36.6", place="Lake Mead")


def test_timeseries_window_selection(tools_env):
    """When the same AOI+index cache holds two seasonal windows for a year, the
    renderer selects the one it's asked for (no silent stale-composite reuse)."""
    import json
    import re

    from _s2_tools import raster, stac, timeseries

    aoi, yr = "-81,26,-80,27", "2020"
    for mf, mt in [("07-01", "09-30"), ("01-01", "04-30")]:
        scenes = stac.search(aoi, f"{yr}-{mf}", f"{yr}-{mt}", use_mock=True)
        ids = [s["scene_id"] for s in scenes]
        for sid in ids:
            raster.fetch_scene_index(sid, aoi, index="mndwi", use_mock=True)
        raster.composite(aoi, f"{yr}-{mf}", f"{yr}-{mt}", scene_ids=ids,
                         index="mndwi", use_mock=True)

    def area_of(bundle):
        h = Path(bundle["html_path"]).read_text()
        cfg = json.loads(re.search(r"var cfg=(\{.*?\}), S=cfg\.series", h, re.S).group(1))
        return cfg["series"][0]["area_km2"]

    dry = area_of(timeseries.render_water_timeseries(
        aoi, index="mndwi", water_threshold=0.0, months_from="01-01", months_to="04-30"))
    summer = area_of(timeseries.render_water_timeseries(
        aoi, index="mndwi", water_threshold=0.0, months_from="07-01", months_to="09-30"))
    assert dry != summer  # the two windows resolve to different composites


def test_unknown_method_rejected(tools_env):
    from _s2_tools import raster, stac

    aoi = "-1,-1,1,1"
    for s in stac.search(aoi, "2024-06-01", "2024-09-30", use_mock=True):
        raster.fetch_scene_index(s["scene_id"], aoi, index="ndvi", use_mock=True)
    c = raster.composite(aoi, "2024-06-01", "2024-09-30", index="ndvi", use_mock=True)
    with pytest.raises(ValueError):
        raster.detect_change(c["relative_path"], c["relative_path"], c["aoi_key"],
                             method="bogus", use_mock=True)


def test_unknown_index_rejected(tools_env):
    from _s2_tools import raster

    with pytest.raises(ValueError):
        raster.fetch_scene_index("S2_X", "-1,-1,1,1", index="bogus", use_mock=True)


def test_grid_size_exact_and_consistent(tools_env):
    """Every scene of an AOI must read to the same exact grid (longest edge =
    max_size), so the composite's np.stack never sees mismatched shapes."""
    from _s2_tools import raster

    assert raster._grid_size([-2.0, 0.0, 0.0, 1.0], 1000) == (1000, 500)  # wide: width pinned
    assert raster._grid_size([0.0, 0.0, 1.0, 2.0], 1000) == (500, 1000)   # tall: height pinned
    # the Okeechobee fitted bbox (nearly square, slightly taller)
    assert raster._grid_size([-81.106, 26.681, -80.611, 27.207], 1024) == (964, 1024)
    # deterministic: same bbox always same grid
    assert raster._grid_size([-1, -1, 1, 1], 512) == raster._grid_size([-1, -1, 1, 1], 512)


def test_mndwi_index(tools_env):
    """MNDWI (green vs SWIR) is a known index and runs through the mock chain —
    the turbid-water index for lakes like Okeechobee."""
    from _s2_tools import raster

    assert raster._BANDS["mndwi"] == ("green", "swir16")
    res = raster.fetch_scene_index("S2_MOCK_2022-07-01_2022-09-30_00", "-81,26,-80,27",
                                   index="mndwi", use_mock=True)
    assert res["cache_type"] == "scene-index" and res["width"] > 0


@pytest.mark.skipif(os.environ.get("S2_LIVE") != "1",
                    reason="live STAC test; set S2_LIVE=1 to run (hits the network)")
def test_real_stac_search_live(tools_env):
    from _s2_tools import stac

    aoi = "-122.50,37.74,-122.40,37.80"
    scenes = stac.search(aoi, "2024-07-01", "2024-07-31", max_cloud=20.0, use_mock=False)
    assert scenes, "no scenes returned for a known-good AOI/window"
    assets = stac.get_item_assets(scenes[0]["scene_id"])
    assert "nir" in assets and "red" in assets and assets["nir"].startswith(("http", "s3"))


# ── provider routing (Sentinel-2 vs Landsat) ────────────────────────────────────


def test_provider_routing(tools_env):
    """A Landsat scene id (starts 'L') routes to Planetary Computer + signing,
    regardless of the collection arg; everything else defaults to Sentinel-2 on
    Earth Search. Pure dict lookup — no network."""
    from _s2_tools import stac

    s2 = stac.provider_for(scene_id="S2A_T12TUL_20240715", collection="sentinel-2-l2a")
    assert s2["collection"] == "sentinel-2-l2a" and s2["sign"] is False
    assert s2["gdal_env"].get("AWS_NO_SIGN_REQUEST") == "YES"

    # scene id wins even when the (stale) collection arg says Sentinel-2.
    ls = stac.provider_for(scene_id="LT05_L2SP_039032_20040911_02_T1",
                           collection="sentinel-2-l2a")
    assert ls["collection"] == "landsat-c2-l2" and ls["sign"] is True
    assert ls["bands"]["nir"] == "nir08"  # Landsat NIR asset key differs
    assert "AWS_NO_SIGN_REQUEST" not in ls["gdal_env"]  # signed Azure, not AWS

    # collection-only routing (no scene id) still works.
    assert stac.provider_for(collection="landsat-c2-l2")["collection"] == "landsat-c2-l2"


@pytest.mark.skipif(os.environ.get("S2_LIVE") != "1",
                    reason="live STAC test; set S2_LIVE=1 to run (hits the network)")
def test_real_landsat_read_live(tools_env):
    """Live Landsat C2 L2 read via Planetary Computer: search -> sign -> window
    read a real NDWI raster (no AWS requester-pays error)."""
    from _s2_tools import raster, stac

    aoi = "-112.45,40.95,-112.25,41.15"  # Great Salt Lake (Antelope Island box)
    scenes = stac.search(aoi, "2004-07-01", "2004-09-30", max_cloud=20.0,
                         collection="landsat-c2-l2", use_mock=False)
    assert scenes and scenes[0]["scene_id"][:1].upper() == "L"
    assets = stac.get_item_assets(scenes[0]["scene_id"])
    assert "blob.core.windows.net" in assets["green"] and "?" in assets["green"]  # signed
    res = raster.fetch_scene_index(scenes[0]["scene_id"], aoi, index="ndwi", use_mock=False)
    assert res["width"] > 0 and res["height"] > 0


# ── handler dispatch ───────────────────────────────────────────────────────────


def test_handlers_dispatch_with_mock(tools_env):
    from sentinel2.handlers.analyze.analyze_handlers import handle_composite
    from sentinel2.handlers.source.source_handlers import (
        handle_fetch_scene_index,
        handle_search_scenes,
    )

    aoi = "-122.55,37.70,-122.35,37.85"
    res = handle_search_scenes({"aoi": aoi, "date_from": "2018-06-01",
                                "date_to": "2018-09-30", "use_mock": True})
    assert res["count"] == len(res["scene_ids"]) > 0
    for sid in res["scene_ids"]:
        handle_fetch_scene_index({"scene_id": sid, "aoi": aoi, "index": "ndvi", "use_mock": True})
    comp = handle_composite({"aoi": aoi, "date_from": "2018-06-01", "date_to": "2018-09-30",
                             "scene_ids": res["scene_ids"], "index": "ndvi", "use_mock": True})
    assert comp["cache_type"] == "composite" and comp["scene_count"] == res["count"]
