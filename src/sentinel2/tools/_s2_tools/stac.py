"""STAC search + asset resolution for Sentinel-2 and Landsat.

Two providers, chosen by collection (and auto-detected from the scene id at
fetch time):

- **Sentinel-2 L2A** via Element84 Earth Search (AWS Open Data) — free, anonymous,
  ~2017→. Bands red/nir/green/swir16; SR = DN * 1e-4.
- **Landsat Collection-2 L2** via Microsoft Planetary Computer — free, but asset
  hrefs need **signing** (a SAS token); covers ~1984→. Bands red/nir08/green/
  swir16; SR = DN * 2.75e-5 − 0.2.

Indices are computed on **surface reflectance** (scale+offset applied) so the two
sensors are comparable in a time series. Search needs only ``requests``; reading
Landsat needs ``planetary-computer`` (``pip install -e ".[landsat]"``). The mock
path is offline.
"""

from __future__ import annotations

from typing import Any

from _s2_tools import s2_mocks

_USER_AGENT = "facetwork-sentinel2-landchange"
_PAGE_LIMIT = 100
_MAX_PAGES = 20

_EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
_PLANETARY_COMPUTER = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Per-collection provider: STAC endpoint, band→asset-key map, reflectance
# scale/offset, and whether asset hrefs must be signed.
PROVIDERS: dict[str, dict[str, Any]] = {
    "sentinel-2-l2a": {
        "collection": "sentinel-2-l2a", "stac": _EARTH_SEARCH, "sign": False,
        "bands": {"red": "red", "nir": "nir", "green": "green", "swir16": "swir16"},
        "scale": 0.0001, "offset": 0.0,
        # Sentinel-2 COGs are on a public AWS bucket — read anonymously.
        "gdal_env": {"AWS_NO_SIGN_REQUEST": "YES", "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"},
    },
    "landsat-c2-l2": {
        "collection": "landsat-c2-l2", "stac": _PLANETARY_COMPUTER, "sign": True,
        "bands": {"red": "red", "nir": "nir08", "green": "green", "swir16": "swir16"},
        "scale": 0.0000275, "offset": -0.2,
        # Signed Azure blobs — a plain /vsicurl read (no AWS env, which would
        # misroute the request).
        "gdal_env": {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"},
    },
}


def provider_for(scene_id: str | None = None, collection: str | None = None) -> dict[str, Any]:
    """Resolve the provider. A Landsat scene id (starts with 'L') wins, so a
    FetchSceneIndex step that only has the id still routes correctly."""
    if scene_id and str(scene_id)[:1].upper() == "L":
        return PROVIDERS["landsat-c2-l2"]
    return PROVIDERS.get(collection or "", PROVIDERS["sentinel-2-l2a"])


def parse_bbox(aoi: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in aoi.split(",")]
    if len(parts) != 4:
        raise ValueError(f"aoi must be 'min_lon,min_lat,max_lon,max_lat' (got {aoi!r})")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def search(
    aoi: str,
    date_from: str,
    date_to: str,
    *,
    max_cloud: float = 20.0,
    collection: str = "sentinel-2-l2a",
    stac_url: str = "",
    exclude_platforms: str = "",
    use_mock: bool = False,
) -> list[dict[str, Any]]:
    """Return scene dicts {scene_id, datetime, cloud_pct}. ``stac_url`` is an
    optional override; by default the collection's provider endpoint is used.
    ``exclude_platforms`` is a comma-separated list of scene-id prefixes to drop
    (e.g. ``"LE07"`` to skip Landsat-7, whose SLC-off gaps stripe the composite)."""
    parse_bbox(aoi)
    if use_mock:
        ids = s2_mocks.mock_scene_ids(aoi, date_from, date_to, max_cloud)
        scenes = [{"scene_id": sid, "datetime": f"{date_from}T10:00:00Z", "cloud_pct": 5.0}
                  for sid in ids]
    else:
        scenes = _search_real(aoi, date_from, date_to, max_cloud, collection, stac_url)
    return _drop_platforms(scenes, exclude_platforms)


def _drop_platforms(scenes: list[dict[str, Any]], exclude_platforms: str) -> list[dict[str, Any]]:
    prefixes = tuple(p.strip() for p in exclude_platforms.split(",") if p.strip())
    if not prefixes:
        return scenes
    return [s for s in scenes if not str(s["scene_id"]).startswith(prefixes)]


def _search_real(aoi, date_from, date_to, max_cloud, collection, stac_url):
    import requests

    prov = provider_for(collection=collection)
    base = (stac_url or prov["stac"]).rstrip("/")
    body = {
        "collections": [prov["collection"]],
        "bbox": list(parse_bbox(aoi)),
        "datetime": f"{date_from}T00:00:00Z/{date_to}T23:59:59Z",
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
        "limit": _PAGE_LIMIT,
    }
    url = base + "/search"
    out: list[dict[str, Any]] = []
    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT
    for _page in range(_MAX_PAGES):
        resp = session.post(url, json=body, timeout=30)
        resp.raise_for_status()
        doc = resp.json()
        for feat in doc.get("features", []):
            props = feat.get("properties", {})
            out.append({
                "scene_id": feat["id"],
                "datetime": props.get("datetime", ""),
                "cloud_pct": float(props.get("eo:cloud_cover", 0.0)),
            })
        nxt = next((lnk for lnk in doc.get("links", []) if lnk.get("rel") == "next"), None)
        if not nxt:
            break
        body = nxt.get("body", body)
        url = nxt.get("href", url)
    return out


def get_item_assets(
    scene_id: str, *, collection: str | None = None, stac_url: str = "",
) -> dict[str, str]:
    """Resolve a scene's band asset hrefs {red,nir,green,swir16}. Landsat hrefs
    (Planetary Computer) are signed with a SAS token so they're readable."""
    import requests

    prov = provider_for(scene_id=scene_id, collection=collection)
    base = (stac_url or prov["stac"]).rstrip("/")
    url = f"{base}/collections/{prov['collection']}/items/{scene_id}"
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30)
    resp.raise_for_status()
    assets = resp.json().get("assets", {})

    sign = None
    if prov["sign"]:
        import planetary_computer as pc

        sign = pc.sign

    hrefs: dict[str, str] = {}
    for band, asset_key in prov["bands"].items():
        asset = assets.get(asset_key)
        if asset and asset.get("href"):
            hrefs[band] = sign(asset["href"]) if sign else asset["href"]
    return hrefs
