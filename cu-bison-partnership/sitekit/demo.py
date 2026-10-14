from __future__ import annotations

"""Synthetic preview data so the layout can be checked offline. Never publish a demo build."""

import numpy as np
from scipy.ndimage import gaussian_filter, zoom

from .config import PROCESSED, record
from .fetch import COVER, build_area, grassland_blocks, make_grid, write_tif

RNG = np.random.default_rng(7)


def _field(shape, scale):
    small = RNG.random((max(2, shape[0] // scale), max(2, shape[1] // scale)))
    big = zoom(small, (shape[0] / small.shape[0], shape[1] / small.shape[1]), order=3)[: shape[0], : shape[1]]
    big = gaussian_filter(big, 2)
    return (big - big.min()) / (big.max() - big.min())


def build_demo(site: dict, manifest: dict) -> None:
    manifest["mode"] = "demo"
    area = build_area(site, manifest)
    bounds = tuple(area.total_bounds)
    t, shp, pixel_m = make_grid(bounds, site["rap"]["map_resolution_m"])
    cols = np.linspace(0, 1, shp[1])[None, :].repeat(shp[0], 0)     # 0 = mountains (west), 1 = plains (east)
    cover = np.zeros((6, *shp), dtype="float32")
    cover[COVER["tree"]] = np.clip(60 * (1 - cols * 4), 0, None) + 5 * _field(shp, 30)
    cover[COVER["perennial"]] = np.clip(15 + 55 * _field(shp, 40) * np.clip(cols * 3, 0, 1), 0, 90)
    cover[COVER["bare"]] = 10 + 40 * (_field(shp, 25) > 0.8)
    grass, blocks = grassland_blocks(cover, t, pixel_m, site["grassland"])
    write_tif(PROCESSED/"rap_perennial_cover.tif", cover[COVER["perennial"]], t)
    write_tif(PROCESSED/"rap_tree_cover.tif", cover[COVER["tree"]], t)
    write_tif(PROCESSED/"open_grassland.tif", np.where(grass, 1.0, np.nan), t)
    blocks.to_file(PROCESSED/"grassland_blocks.geojson", driver="GeoJSON")
    manifest["latest_rap_year"] = 2024
    record(manifest, "rap", status="demo", source="Synthetic preview data", url="",
           note="Not real data. Rebuild with `python scripts/build_data.py` before sharing.")

    # Synthetic mask and explicit inventories for the preview validation contract.
    write_tif(PROCESSED / "rangeland_mask.tif", np.ones(shp, dtype=float), t)
    record(manifest, "landcover", status="demo", source="Synthetic preview mask", url="")
    inventories = {"area": ["area.geojson"], "landcover": ["rangeland_mask.tif"],
                   "rap": [p.name for p in PROCESSED.glob("rap_*")]}
    inventories["rap"] += ["open_grassland.tif", "grassland_blocks.geojson"]
    for key, files in inventories.items():
        manifest["datasets"][key]["files"] = files
