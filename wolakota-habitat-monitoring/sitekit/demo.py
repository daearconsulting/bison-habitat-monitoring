"""Synthetic stand-in data so the site can be previewed without internet access.

Every page shows a large "PREVIEW DATA" banner when these files are in use.
Never publish a demo build; the GitHub Actions workflow always builds real data.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box

from .config import CRS_AREA, CRS_GEO, PROCESSED, record
from .fetch import area_mask, make_grid, write_tif

RNG = np.random.default_rng(42)


def _smooth_field(shape, scale=25):
    """Smooth random field (0-1) built from low-frequency noise."""
    small = RNG.random((max(2, shape[0] // scale), max(2, shape[1] // scale)))
    from scipy.ndimage import gaussian_filter, zoom
    big = zoom(small, (shape[0] / small.shape[0], shape[1] / small.shape[1]), order=3)
    big = gaussian_filter(big[: shape[0], : shape[1]], 3)
    return (big - big.min()) / (big.max() - big.min())


def build_demo(site: dict, manifest: dict) -> None:
    manifest["mode"] = "demo"
    PROCESSED.mkdir(parents=True, exist_ok=True)
    bbox = site["area"].get("clip_bbox") or [-101.0, 43.0, -100.2, 43.6]
    area = gpd.GeoDataFrame({"label": [site["area"]["label"]]},
                            geometry=[box(*bbox).buffer(-0.02)], crs=CRS_GEO)
    area["acres"] = area.to_crs(CRS_AREA).area / 4046.86
    area.to_file(PROCESSED / "area.geojson", driver="GeoJSON")
    bounds = tuple(area.total_bounds)

    # Yearly vegetation series with drought dips (2002, 2012, 2017, 2021)
    years = np.arange(1986, 2025)
    rain = 1 + 0.15 * RNG.standard_normal(len(years))
    for dry in (2002, 2006, 2012, 2017, 2021):
        rain[years == dry] -= 0.35
    pfg = np.clip(1150 * rain, 300, None)
    afg = np.clip(90 + 2.2 * (years - 1986) + 40 * RNG.standard_normal(len(years)), 20, None)
    series = pd.DataFrame({
        "year": years,
        "cover_annual_grass_forb_pct": np.clip(4 + 0.12 * (years - 1986) + RNG.normal(0, 1, len(years)), 1, None),
        "cover_bare_ground_pct": np.clip(9 - 3 * (rain - 1) + RNG.normal(0, 1, len(years)), 2, None),
        "cover_litter_pct": 18 + RNG.normal(0, 1.5, len(years)),
        "cover_perennial_grass_forb_pct": np.clip(52 * rain, 20, 80),
        "cover_shrub_pct": 3 + 0.03 * (years - 1986),
        "cover_tree_pct": 2.5 + 0.04 * (years - 1986),
        "forage_annual_grass_forb_lbs_ac": afg,
        "forage_perennial_grass_forb_lbs_ac": pfg,
    })
    series["forage_total_lbs_ac"] = series.forage_annual_grass_forb_lbs_ac + series.forage_perennial_grass_forb_lbs_ac
    series.to_csv(PROCESSED / "rap_annual.csv", index=False)
    manifest["latest_rap_year"] = int(years[-1])

    t, shape, (dy, dx) = make_grid(bounds, site["rap"]["map_resolution_m"])
    inside = area_mask(area, t, shape)
    base = _smooth_field(shape)
    write_tif(PROCESSED / "rap_perennial_cover.tif", np.where(inside, 25 + 50 * base, np.nan), t)
    write_tif(PROCESSED / "rap_annual_cover.tif", np.where(inside, 2 + 14 * _smooth_field(shape, 15) ** 2, np.nan), t)
    write_tif(PROCESSED / "rap_forage.tif", np.where(inside, 500 + 1300 * base, np.nan), t)

    ts, shape_s, _ = make_grid(bounds, site["rap"]["series_resolution_m"])
    inside_s = area_mask(area, ts, shape_s)
    write_tif(PROCESSED / "rap_forage_anomaly.tif",
              np.where(inside_s, -35 + 50 * _smooth_field(shape_s, 8), np.nan), ts)
    write_tif(PROCESSED / "rap_annual_change.tif",
              np.where(inside_s, -2 + 9 * _smooth_field(shape_s, 6) ** 2, np.nan), ts)

    # Water: a few wandering streams and ponds
    streams = []
    for k in range(4):
        y0 = bbox[1] + (k + 1) * (bbox[3] - bbox[1]) / 5
        xs = np.linspace(bbox[0], bbox[2], 40)
        ys = y0 + 0.03 * np.sin(np.linspace(0, 6, 40) + k) + RNG.normal(0, 0.004, 40)
        streams.append(LineString(zip(xs, ys)))
    ponds = [Point(RNG.uniform(bbox[0], bbox[2]), RNG.uniform(bbox[1], bbox[3])).buffer(0.004) for _ in range(40)]
    s = gpd.clip(gpd.GeoDataFrame(geometry=streams, crs=CRS_GEO), area)
    p = gpd.clip(gpd.GeoDataFrame(geometry=ponds, crs=CRS_GEO), area)
    s.to_file(PROCESSED / "water_streams.geojson", driver="GeoJSON")
    p.to_file(PROCESSED / "water_bodies.geojson", driver="GeoJSON")
    from rasterio.features import rasterize
    from scipy.ndimage import distance_transform_edt
    water = rasterize([(g, 1) for g in list(s.geometry) + list(p.geometry)], out_shape=shape,
                      transform=t, all_touched=True).astype(bool)
    write_tif(PROCESSED / "water_distance_km.tif",
              np.where(inside, distance_transform_edt(~water, sampling=(dy, dx)) / 1000, np.nan), t)

    # Drought: weekly categories with dry spells
    dates = pd.date_range("2000-01-04", "2025-09-30", freq="7D")
    frames = []
    for county in site["drought_counties"].values():
        severity = np.clip(np.convolve(RNG.normal(0, 1, len(dates)), np.ones(30) / 6, "same"), -3, 3)
        cats = {c: np.zeros(len(dates)) for c in ["none", "d0", "d1", "d2", "d3", "d4"]}
        for i, v in enumerate(severity):
            level = int(np.clip(np.floor(v + 1.2), -1, 4))
            if level < 0:
                cats["none"][i] = 100
            else:
                key = f"d{level}"
                cats[key][i] = 70
                cats["d0" if level > 0 else "none"][i] += 30
        df = pd.DataFrame({"date": dates, **cats})
        df["county"] = county
        frames.append(df)
    pd.concat(frames).to_csv(PROCESSED / "drought_weekly.csv", index=False)

    # Fire: a handful of perimeters
    fires = []
    for yr in [2002, 2006, 2012, 2012, 2016, 2021]:
        c = Point(RNG.uniform(bbox[0], bbox[2]), RNG.uniform(bbox[1], bbox[3]))
        fires.append({"year": yr, "name": f"Example fire {yr}", "geometry": c.buffer(RNG.uniform(0.01, 0.04))})
    f = gpd.clip(gpd.GeoDataFrame(fires, crs=CRS_GEO), area)
    f["acres"] = f.to_crs(CRS_AREA).area / 4046.86
    f["acres_in_area"] = f["acres"]
    f.to_file(PROCESSED / "fire_perimeters.geojson", driver="GeoJSON")

    for key in ["area", "rap", "drought", "water", "fire"]:
        record(manifest, key, status="demo", source="Synthetic preview data", url="",
               note="Not real data. Rebuild with `python scripts/build_data.py` before sharing.")

    # Synthetic mask and explicit inventories for the preview validation contract.
    write_tif(PROCESSED / "rangeland_mask.tif", np.ones(shape, dtype=float), t)
    record(manifest, "landcover", status="demo", source="Synthetic preview mask", url="")
    inventories = {"area": ["area.geojson"], "landcover": ["rangeland_mask.tif"],
                   "rap": [p.name for p in PROCESSED.glob("rap_*")]}
    inventories.update(drought=["drought_weekly.csv"], water=[p.name for p in PROCESSED.glob("water_*")], fire=["fire_perimeters.geojson"])
    for key, files in inventories.items():
        manifest["datasets"][key]["files"] = files
