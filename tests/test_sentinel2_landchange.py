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


@pytest.mark.skipif(os.environ.get("S2_LIVE") != "1",
                    reason="live STAC test; set S2_LIVE=1 to run (hits the network)")
def test_real_stac_search_live(tools_env):
    from _s2_tools import stac

    aoi = "-122.50,37.74,-122.40,37.80"
    scenes = stac.search(aoi, "2024-07-01", "2024-07-31", max_cloud=20.0, use_mock=False)
    assert scenes, "no scenes returned for a known-good AOI/window"
    assets = stac.get_item_assets(scenes[0]["scene_id"])
    assert "nir" in assets and "red" in assets and assets["nir"].startswith(("http", "s3"))


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
