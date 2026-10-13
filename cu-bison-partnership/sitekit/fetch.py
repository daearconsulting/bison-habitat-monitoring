"""Download public data and write small, site-ready products to data/processed/.

One data source is used: the Rangeland Analysis Platform (RAP) v3, yearly
vegetation cover from Landsat satellite images and field plots. From it this
module makes a coarse "where is open grassland/shrubland vegetation" screen and finds
contiguous grassland blocks large enough to be worth a conversation.

It deliberately does NOT use land ownership. Who owns or manages a block, and
whether they would ever consider a herd, is a conversation for people, not a
dataset. Ownership layers (e.g., Colorado COMaP or USGS PAD-US) can be added
later as a separate, optional step.
"""
from __future__ import annotations

import logging
from datetime import date

import geopandas as gpd
import numpy as np
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds
from scipy.ndimage import label
from shapely.geometry import box, shape
from shapely.validation import make_valid
from shapely import set_precision

from .config import CRS_AREA, CRS_GEO, PROCESSED, record

log = logging.getLogger("sitekit.fetch")

RAP_BASES = ["https://rangeland.ntsg.umt.edu/data/rap", "http://rangeland.ntsg.umt.edu/data/rap"]
# Band order in vegetation-cover files
COVER = {"annual": 0, "bare": 1, "litter": 2, "perennial": 3, "shrub": 4, "tree": 5}
M_PER_DEG = 111_320.0


def make_grid(bounds, res_m: float):
    """Lat/lon grid with pixels about res_m on a side; also returns pixel size in meters."""
    minx, miny, maxx, maxy = bounds
    mid = np.deg2rad((miny + maxy) / 2)
    dlat, dlon = res_m / M_PER_DEG, res_m / (M_PER_DEG * np.cos(mid))
    cols, rows = int(np.ceil((maxx - minx) / dlon)), int(np.ceil((maxy - miny) / dlat))
    t = from_bounds(minx, miny, maxx, maxy, cols, rows)
    return t, (rows, cols), ((maxy-miny)/rows * M_PER_DEG, (maxx-minx)/cols * M_PER_DEG * np.cos(mid))


def write_tif(path, arr, transform) -> None:
    profile = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="float32",
                   crs=CRS_GEO, transform=transform, nodata=np.nan, compress="deflate")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype("float32"), 1)


def build_area(site: dict, manifest: dict) -> gpd.GeoDataFrame:
    a = site["area"]
    gdf = gpd.GeoDataFrame({"label": [a["label"]]}, geometry=[box(*a["bbox"])], crs=CRS_GEO)
    gdf["acres"] = gdf.to_crs(CRS_AREA).area / 4046.86
    PROCESSED.mkdir(parents=True, exist_ok=True)
    gdf.to_file(PROCESSED / "area.geojson", driver="GeoJSON")
    record(manifest, "area", status="ok", source="Screening box set in site.yaml", url="",
           files=["area.geojson"])
    return gdf


def _rap_url(year: int, base: str) -> str:
    return f"{base}/rap-vegetation-cover/v3/vegetation-cover-v3-{year}.tif"


def latest_rap_year() -> int:
    for y in range(date.today().year, date.today().year - 4, -1):
        for base in RAP_BASES:
            try:
                if requests.head(_rap_url(y, base), timeout=30, allow_redirects=True).status_code == 200:
                    return y
            except requests.RequestException:
                pass
    raise RuntimeError("Could not reach the Rangeland Analysis Platform")


def read_cover(year: int, bounds, out_shape) -> np.ndarray:
    for base in RAP_BASES:
        try:
            with rasterio.open(_rap_url(year, base)) as src:
                if src.crs != rasterio.crs.CRS.from_epsg(4326):
                    raise ValueError("RAP source CRS must be EPSG:4326")
                win = window_from_bounds(*bounds, transform=src.transform)
                data = src.read(list(range(1, 7)), window=win, out_shape=(6, *out_shape),
                                resampling=Resampling.average, boundless=True, masked=True)
            return data.astype("float32").filled(np.nan)
        except Exception as exc:
            log.debug("RAP read failed (%s): %s", base, exc)
    raise RuntimeError(f"Could not read RAP cover for {year}")


def grassland_blocks(cover: np.ndarray, transform, pixel_m: tuple[float, float], rules: dict, eligible=None):
    """Mark open grassland pixels, group touching pixels, keep large groups.

    Returns (grass_mask, blocks GeoDataFrame with acres per block).
    """
    with np.errstate(invalid="ignore"):
        grass = ((cover[COVER["perennial"]] >= rules["min_perennial_cover_pct"])
                 & (cover[COVER["tree"]] <= rules["max_tree_cover_pct"])
                 & (cover[COVER["bare"]] <= rules["max_bare_ground_pct"]))
    if eligible is not None:
        grass &= eligible
    labels, n = label(grass, structure=np.ones((3, 3)))   # 8-neighbor grouping
    pixel_acres = pixel_m[0] * pixel_m[1] / 4046.86
    counts = np.bincount(labels.ravel())
    keep_ids = np.where(counts * pixel_acres >= rules["min_block_acres"])[0]
    keep_ids = keep_ids[keep_ids != 0]
    kept = np.isin(labels, keep_ids)
    geoms, ids = [], []
    for geom, val in shapes(np.where(kept, labels, 0).astype("int32"), mask=kept, transform=transform):
        geoms.append(shape(geom))
        ids.append(int(val))
    blocks = gpd.GeoDataFrame({"block": ids}, geometry=geoms, crs=CRS_GEO).dissolve("block").reset_index()
    blocks["acres"] = blocks.to_crs(CRS_AREA).area / 4046.86
    blocks = blocks.sort_values("acres", ascending=False).reset_index(drop=True)
    blocks["block"] = np.arange(1, len(blocks) + 1)
    blocks["geometry"] = blocks.geometry.apply(make_valid).simplify(0.0008).apply(make_valid).apply(lambda g: set_precision(g, 1e-7))
    return grass, blocks


def build_grassland(site: dict, area: gpd.GeoDataFrame, manifest: dict) -> None:
    bounds = tuple(area.total_bounds)
    t, shp, pixel_m = make_grid(bounds, site["rap"]["map_resolution_m"])
    year = latest_rap_year()
    cover = read_cover(year, bounds, shp)
    from .landcover import grazing_mask
    eligible = grazing_mask(site, bounds, shp, manifest)
    valid = eligible & np.isfinite(cover).all(axis=0)
    if not eligible.any() or valid.sum() / eligible.sum() < 0.9:
        raise ValueError("Insufficient valid RAP data on eligible rangeland")
    grass, blocks = grassland_blocks(cover, t, pixel_m, site["grassland"], eligible)
    write_tif(PROCESSED / "rap_perennial_cover.tif", cover[COVER["perennial"]], t)
    write_tif(PROCESSED / "rap_tree_cover.tif", cover[COVER["tree"]], t)
    write_tif(PROCESSED / "open_grassland.tif", np.where(grass, 1.0, np.nan), t)
    blocks.to_file(PROCESSED / "grassland_blocks.geojson", driver="GeoJSON", COORDINATE_PRECISION=7)
    manifest["latest_rap_year"] = year
    record(manifest, "rap", status="ok",
           source="Rangeland Analysis Platform v3 (USDA-NRCS, BLM, Univ. of Montana)",
           url="https://rangelands.app/", note=f"Vegetation cover, {year}; {len(blocks)} blocks found",
           files=["rap_perennial_cover.tif", "rap_tree_cover.tif", "open_grassland.tif", "grassland_blocks.geojson"])


