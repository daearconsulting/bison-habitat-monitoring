"""Fixed-vintage NLCD grassland/shrubland mask, sampled categorically.

Classes 52 and 71 only: excludes mapped crops, hay/pasture, development,
forest, water and wetlands. This is not a native-species or irrigation map.
"""
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.transform import from_bounds
from .config import PROCESSED, record

def grazing_mask(site, bounds, shape, manifest):
    cfg = site["landcover"]
    transform = from_bounds(*bounds, shape[1], shape[0])
    with rasterio.open(cfg["raster"]) as src:
        if src.crs is None:
            raise ValueError("Land cover raster lacks a CRS")
        with WarpedVRT(src, crs="EPSG:4326", transform=transform,
                       width=shape[1], height=shape[0], resampling=Resampling.nearest) as vrt:
            classes = vrt.read(1, masked=True).filled(0)
    eligible = np.isin(classes, cfg["include_classes"])
    # Cell areas on the geographic grid, measured on the WGS84 ellipsoid.
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    row_acres = []
    west = bounds[0]
    for row in range(shape[0]):
        north = transform.f + row * transform.e
        south = north + transform.e
        area, _ = geod.polygon_area_perimeter([west, west+transform.a, west+transform.a, west], [south,south,north,north])
        row_acres.append(abs(area)/4046.8564224)
    region = __import__("geopandas").read_file(PROCESSED / "area.geojson")
    from rasterio.features import geometry_mask
    inside = geometry_mask(region.geometry, out_shape=shape, transform=transform, invert=True)
    manifest["eligible_acres"] = float((eligible & inside).sum(axis=1) @ np.asarray(row_acres))
    manifest["eligible_region_pct"] = float(100 * (eligible & inside).sum() / max(1,inside.sum()))
    if not eligible.any():
        raise ValueError("No eligible NLCD grassland/shrubland cells")
    from .fetch import write_tif
    write_tif(PROCESSED / "rangeland_mask.tif", eligible.astype(float), transform)
    record(manifest, "landcover", status="ok", source=f"Annual NLCD {cfg['year']} (fixed-vintage mask)",
           url=cfg["source_url"], files=["rangeland_mask.tif"],
           note="Classes 52/71; excludes crops, hay/pasture and developed land. Does not establish native species or water reliability.")
    manifest["eligible_grid_fraction_pct"] = float(100 * eligible.mean())
    return eligible
