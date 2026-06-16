"""Multi-year surface-water time series → a MapLibre viewer with a year slider.

Discovers the per-year NDWI composites already in the cache (one per year, from
the ScanYears fan-out), turns each into a water-extent tile layer (blue where
``index > water_threshold``), and renders one HTML viewer with a **year slider /
tab bar** that switches the active year over a basemap, plus a Chart.js line
chart of water area (km²) over time. So you scrub the years and watch the lake
shrink.

Output bundle: ``output/s2-timeseries/<aoi_key>/{index.html, tiles/<year>/{z}/{x}/{y}.png}``.
Honest range note: Sentinel-2 starts ~2017, so a true 20-year span needs a
Landsat source (requester-pays on AWS / signed on Planetary Computer) — a
drop-in s2.source sibling.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Any

from _s2_tools import map_render, raster, sidecar, storage

_WATER_RGB = (33, 102, 172)  # blue


def _area_km2(bounds, shape, n_px: int) -> float:
    w, s, e, n = (float(b) for b in bounds)
    h, wid = shape
    latm = (s + n) / 2
    px = ((n - s) / h * 111.32) * ((e - w) / wid * 111.32 * math.cos(math.radians(latm)))
    return n_px * px


def render_water_timeseries(
    aoi: str, *, index: str = "ndwi", water_threshold: float = 0.1,
    title: str = "Surface water over time", basemap_url: str = "",
) -> dict[str, Any]:
    ak = raster.aoi_key(aoi)
    # Discover per-year composites: COMPOSITE/<ak>/<index>/<YYYY>-..._<YYYY>-....npz
    rels = [r for r in sidecar.list_entries(raster.COMPOSITE) if r.startswith(f"{ak}/{index}/")]
    by_year: dict[str, str] = {}
    for r in rels:
        fn = r.rsplit("/", 1)[-1]
        yr = fn[:4]
        if yr.isdigit():
            by_year[yr] = r  # one composite per year window
    years = sorted(by_year)
    if not years:
        raise FileNotFoundError(f"no per-year composites for aoi={ak} index={index}; run ScanYears")

    out_dir = storage.join(storage.output_root(), "s2-timeseries", ak)
    tiles_root = storage.join(out_dir, "tiles")

    try:
        import morecantile
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds
        from rio_tiler.io import Reader
        geo = True
    except ImportError:
        geo = False

    series: list[dict[str, Any]] = []
    bounds_out = None
    minz = maxz = None
    for yr in years:
        arr, bounds, _crs = raster._load(raster.COMPOSITE, by_year[yr])
        bounds_out = [float(b) for b in bounds]
        water = arr > water_threshold
        series.append({"year": yr, "area_km2": round(_area_km2(bounds, arr.shape, int(water.sum())), 1)})
        if not geo:
            continue
        h, w = arr.shape
        rgb = np.zeros((3, h, w), dtype="uint8")
        for i, c in enumerate(_WATER_RGB):
            rgb[i][water] = c
        mask = (water * 255).astype("uint8")
        west, south, east, north = bounds_out
        if minz is None:
            minz, maxz = map_render._zoom_range(west, south, east, north, max(w, h))
        profile = dict(driver="GTiff", height=h, width=w, count=3, dtype="uint8",
                       crs="EPSG:4326", transform=from_bounds(west, south, east, north, w, h),
                       photometric="RGB", compress="deflate", tiled=True,
                       blockxsize=256, blockysize=256)
        tms = morecantile.tms.get("WebMercatorQuad")
        with tempfile.TemporaryDirectory() as td:
            local = os.path.join(td, "w.tif")
            with rasterio.open(local, "w", **profile) as dst:
                dst.write(rgb)
                dst.write_mask(mask)
            ytiles = storage.join(tiles_root, yr)
            with Reader(local, tms=tms) as r:
                for z in range(minz, maxz + 1):
                    for t in tms.tiles(west, south, east, north, [z]):
                        try:
                            img = r.tile(t.x, t.y, t.z)
                        except Exception:
                            continue
                        storage.write_bytes(
                            storage.join(ytiles, str(t.z), str(t.x), f"{t.y}.png"),
                            img.render(img_format="PNG", add_mask=True))

    html = _html(title, series, bounds_out, minz, maxz, geo, basemap_url)
    html_path = storage.join(out_dir, "index.html")
    storage.write_text(html_path, html)
    return {"aoi_key": ak, "output_dir": out_dir, "html_path": html_path,
            "year_count": len(years)}


def _html(title, series, bounds, minz, maxz, geo, basemap_url) -> str:
    basemap = [basemap_url] if basemap_url else map_render._BASEMAP
    cfg = {"series": series, "bounds": bounds, "minz": minz, "maxz": maxz,
           "basemap": basemap, "basemapAttr": map_render._BASEMAP_ATTR, "geo": geo}
    return _TS_HTML.replace("__TITLE__", title).replace("__CFG__", json.dumps(cfg))


_TS_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
 body{margin:0;font-family:system-ui}#m{position:absolute;inset:0}
 .panel{position:absolute;left:16px;bottom:16px;width:340px;background:#fff;border-radius:8px;
   box-shadow:0 1px 6px rgba(0,0,0,.3);padding:12px 14px;z-index:1}
 .panel h3{margin:0 0 2px;font-size:15px}.panel .sub{color:#555;font-size:12px;margin-bottom:8px}
 .yearrow{display:flex;align-items:center;gap:8px;margin:6px 0}
 .yearrow input{flex:1}
 .ybadge{font:600 13px ui-monospace,monospace;min-width:40px}
 .area{font:600 13px ui-monospace,monospace;color:#2166ac}
 .tabs{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 8px}
 .tabs button{font:600 11px system-ui;border:1px solid #ccd;background:#f4f6fb;border-radius:6px;padding:3px 7px;cursor:pointer}
 .tabs button.on{background:#2166ac;color:#fff;border-color:#2166ac}
 canvas{margin-top:6px}
</style></head><body>
<div id="m"></div>
<div class="panel">
 <h3>__TITLE__</h3><div class="sub">water extent (NDWI) — scrub the years</div>
 <div class="tabs" id="tabs"></div>
 <div class="yearrow"><span class="ybadge" id="ylabel"></span>
   <input type="range" id="slider" min="0" value="0" step="1">
   <span class="area" id="area"></span></div>
 <canvas id="chart" height="120"></canvas>
</div>
<script>
var cfg=__CFG__, S=cfg.series, n=S.length;
var map=new maplibregl.Map({container:'m',style:{version:8,sources:{base:{type:'raster',tiles:cfg.basemap,tileSize:256,attribution:cfg.basemapAttr}},layers:[{id:'base',type:'raster',source:'base'}]}});
map.addControl(new maplibregl.NavigationControl());
function layerId(i){return 'water-'+S[i].year;}
map.on('load',function(){
  if(cfg.geo){ S.forEach(function(s,i){
    map.addSource(layerId(i),{type:'raster',tiles:['tiles/'+s.year+'/{z}/{x}/{y}.png'],tileSize:256,minzoom:cfg.minz,maxzoom:cfg.maxz,bounds:cfg.bounds});
    map.addLayer({id:layerId(i),type:'raster',source:layerId(i),paint:{'raster-opacity':0.8},layout:{visibility:i===0?'visible':'none'}});
  });}
  if(cfg.bounds) map.fitBounds([[cfg.bounds[0],cfg.bounds[1]],[cfg.bounds[2],cfg.bounds[3]]],{padding:30});
});
var slider=document.getElementById('slider');slider.max=n-1;
var tabs=document.getElementById('tabs');
S.forEach(function(s,i){var b=document.createElement('button');b.textContent=s.year;b.onclick=function(){show(i);};tabs.appendChild(b);});
function show(i){
  slider.value=i;
  document.getElementById('ylabel').textContent=S[i].year;
  document.getElementById('area').textContent=S[i].area_km2+' km²';
  tabs.querySelectorAll('button').forEach(function(b,j){b.classList.toggle('on',j===i);});
  if(cfg.geo&&map.getLayer)S.forEach(function(s,j){if(map.getLayer(layerId(j)))map.setLayoutProperty(layerId(j),'visibility',j===i?'visible':'none');});
  if(window._chart){window._chart.data.datasets[0].pointRadius=S.map(function(_,j){return j===i?6:3;});window._chart.update();}
}
slider.oninput=function(){show(+slider.value);};
new Chart(document.getElementById('chart'),{type:'line',
  data:{labels:S.map(function(s){return s.year;}),datasets:[{label:'water km²',data:S.map(function(s){return s.area_km2;}),borderColor:'#2166ac',backgroundColor:'rgba(33,102,172,.15)',fill:true,tension:.25,pointRadius:3}]},
  options:{plugins:{legend:{display:false}},onClick:function(e,el){if(el.length)show(el[0].index);},scales:{y:{title:{display:true,text:'km²'}}}}});
window._chart=Chart.getChart('chart');
show(0);
</script></body></html>
"""
