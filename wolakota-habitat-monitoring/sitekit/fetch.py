"""Download public data and write small, site-ready products to data/processed/.

Run through scripts/build_data.py (locally or in GitHub Actions). Each step is
independent: if one data service is down, that step is recorded as "failed" in
the manifest, the others still run, and the matching page says the data is
missing instead of breaking the whole site.

Sources (all public, no logins):
  * Census TIGER/Line AIANNH ............ study-area boundary
  * Rangeland Analysis Platform (RAP) v3 . yearly vegetation cover and forage (biomass)
  * U.S. Drought Monitor data services .... weekly drought by county
  * USGS NHDPlus High Resolution .......... streams, ponds, and reservoirs
  * NIFC InterAgency Fire Perimeter History  past fire perimeters
"""
from __future__ import annotations

import io
import logging
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, rasterize
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds
from scipy.ndimage import distance_transform_edt
from shapely.geometry import box
from shapely.validation import make_valid

from .config import CACHE, CRS_AREA, CRS_GEO, PROCESSED, record

log = logging.getLogger("sitekit.fetch")

TIGER_AIANNH = "https://www2.census.gov/geo/tiger/TIGER2023/AIANNH/tl_2023_us_aiannh.zip"
RAP_BASES = ["https://rangeland.ntsg.umt.edu/data/rap", "http://rangeland.ntsg.umt.edu/data/rap"]
# RAP band order (documented by the RAP team and the rapr package)
RAP_COVER_BANDS = ["annual_grass_forb", "bare_ground", "litter", "perennial_grass_forb", "shrub", "tree"]
RAP_BIOMASS_BANDS = ["annual_grass_forb", "perennial_grass_forb"]
USDM_COUNTY = ("https://usdmdataservices.unl.edu/api/CountyStatistics/"
               "GetDroughtSeverityStatisticsByAreaPercent")
NHD_FLOWLINES = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3/query"
NHD_WATERBODIES = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/9/query"
NIFC_FIRES = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
              "InterAgencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query")

# NHD feature codes: 46006 = perennial stream. Intermittent streams (46003) are
# left out of "distance to water" because they cannot be counted on in late summer.
PERENNIAL_FCODES = {46006}

M_PER_DEG = 111_320.0


# Study area and grid

def build_area(site: dict, manifest: dict) -> gpd.GeoDataFrame:
    """Write data/processed/area.geojson and return it (EPSG:4326)."""
    area = site["area"]
    if area.get("boundary_file"):
        gdf = gpd.read_file(area["boundary_file"]).to_crs(CRS_GEO)
        src, url = "User-supplied boundary file", str(area["boundary_file"])
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        cached = CACHE / "tl_2023_us_aiannh.zip"
        if not cached.exists():
            log.info("Downloading Census AIANNH boundaries ...")
            r = requests.get(TIGER_AIANNH, timeout=600)
            r.raise_for_status()
            cached.write_bytes(r.content)
        with zipfile.ZipFile(cached) as z, tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            all_areas = gpd.read_file(next(Path(tmp).glob("*.shp"))).to_crs(CRS_GEO)
        gdf = all_areas[all_areas["NAME"] == area["census_aiannh_name"]].copy()
        if gdf.empty:
            raise ValueError(f"No Census AIANNH area named {area['census_aiannh_name']!r}")
        src, url = "U.S. Census Bureau TIGER/Line 2023 (AIANNH)", TIGER_AIANNH

    gdf = gdf.dissolve().reset_index(drop=True)
    gdf["geometry"] = gdf.geometry.apply(make_valid)
    if area.get("clip_bbox"):
        gdf = gpd.clip(gdf, box(*area["clip_bbox"]))
    if gdf.empty or not gdf.to_crs(CRS_AREA).area.sum() > 0:
        raise ValueError("Study area is empty after clipping")
    gdf = gdf[["geometry"]]
    gdf["label"] = area["label"]
    gdf["acres"] = gdf.to_crs(CRS_AREA).area / 4046.86

    PROCESSED.mkdir(parents=True, exist_ok=True)
    gdf.to_file(PROCESSED / "area.geojson", driver="GeoJSON")
    record(manifest, "area", status="ok", source=src, url=url,
           note="Regional extent for illustration; not a management boundary.",
           files=["area.geojson"])
    return gdf


def make_grid(bounds, res_m: float):
    """A lat/lon grid over `bounds` with pixels about `res_m` meters on a side.

    Returns (transform, (rows, cols), (dy_m, dx_m)). The pixel size in meters
    is returned too, because distances computed on a lat/lon grid need it.
    """
    minx, miny, maxx, maxy = bounds
    mid_lat = np.deg2rad((miny + maxy) / 2)
    dlat = res_m / M_PER_DEG
    dlon = res_m / (M_PER_DEG * np.cos(mid_lat))
    cols = int(np.ceil((maxx - minx) / dlon))
    rows = int(np.ceil((maxy - miny) / dlat))
    transform = from_bounds(minx, miny, maxx, maxy, cols, rows)
    return transform, (rows, cols), ((maxy-miny)/rows * M_PER_DEG, (maxx-minx)/cols * M_PER_DEG * np.cos(mid_lat))


def area_mask(gdf, transform, shape) -> np.ndarray:
    """True for pixels inside the study area."""
    return geometry_mask(gdf.geometry, out_shape=shape, transform=transform, invert=True)


def write_tif(path: Path, arr: np.ndarray, transform) -> None:
    profile = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                   dtype="float32", crs=CRS_GEO, transform=transform, nodata=np.nan,
                   compress="deflate")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype("float32"), 1)


# Rangeland Analysis Platform

def _rap_url(product: str, year: int, base: str) -> str:
    # e.g. .../rap-vegetation-cover/v3/vegetation-cover-v3-2023.tif
    return f"{base}/rap-{product}/v3/{product}-v3-{year}.tif"


def _read_rap(product: str, year: int, bands: int, bounds, shape) -> np.ndarray | None:
    """Read a RAP year for our area, resampled (averaged) onto our grid.

    RAP files are cloud-optimized GeoTIFFs covering the western U.S., so we read
    only the window we need straight over the web instead of downloading them.
    Returns an array (bands, rows, cols) with NaN outside valid data, or None.
    """
    for base in RAP_BASES:
        url = _rap_url(product, year, base)
        try:
            with rasterio.Env(GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="5"):
                with rasterio.open(url) as src:
                    if src.crs != rasterio.crs.CRS.from_epsg(4326):
                        raise ValueError("RAP source CRS must be EPSG:4326")
                    win = window_from_bounds(*bounds, transform=src.transform)
                    data = src.read(list(range(1, bands + 1)), window=win, out_shape=(bands, *shape),
                                    resampling=Resampling.average, boundless=True, masked=True)
            return data.astype("float32").filled(np.nan)
        except Exception as exc:  # try the next base URL, then give up on this year
            log.debug("RAP read failed for %s: %s", url, exc)
    return None


def latest_rap_year(first_guess: int | None = None) -> int:
    """Find the most recent year RAP has published (it lags by a few months)."""
    year = first_guess or date.today().year
    for y in range(year, year - 4, -1):
        for base in RAP_BASES:
            try:
                r = requests.head(_rap_url("vegetation-cover", y, base), timeout=30, allow_redirects=True)
                if r.status_code == 200:
                    return y
            except requests.RequestException:
                pass
    raise RuntimeError("Could not reach the Rangeland Analysis Platform")


def build_rap(site: dict, area: gpd.GeoDataFrame, manifest: dict) -> None:
    """Yearly vegetation summary + a few maps for the pages.

    Products:
      rap_annual.csv           area-average cover (%) and forage (lbs/acre), every year
      rap_perennial_cover.tif  latest perennial grass and forb cover (%)
      rap_annual_cover.tif     latest annual grass and forb cover (%) (cheatgrass/brome signal)
      rap_forage.tif           latest herbaceous forage production (lbs/acre)
      rap_forage_anomaly.tif   latest forage compared with the area's long-term normal (%)
      rap_annual_change.tif    change in annual grass cover, recent 5 years vs first 10 years
    """
    rap = site["rap"]
    bounds = tuple(area.total_bounds)
    last = latest_rap_year()
    years = list(range(rap["first_year"], last + 1))

    # 1. Long-term series on a coarse grid (fast; enough for area averages)
    t_s, shape_s, _ = make_grid(bounds, rap["series_resolution_m"])
    from .landcover import grazing_mask
    inside_s = area_mask(area, t_s, shape_s) & grazing_mask(site, bounds, shape_s, manifest)
    if not inside_s.any():
        raise ValueError("No eligible rangeland cells in study area")
    rows, forage_stack, annual_stack = [], {}, {}
    for y in years:
        cover = _read_rap("vegetation-cover", y, 6, bounds, shape_s)
        biomass = _read_rap("vegetation-biomass", y, 2, bounds, shape_s)
        if cover is None or biomass is None:
            log.warning("RAP %s unavailable; skipping", y)
            continue
        valid = inside_s & np.isfinite(cover).all(axis=0) & np.isfinite(biomass).all(axis=0)
        coverage = valid.sum() / inside_s.sum()
        if coverage < 0.9:
            raise ValueError(f"RAP {y} has only {coverage:.1%} valid eligible pixels")
        row = {"year": y, "valid_coverage_pct": 100 * coverage}
        for i, name in enumerate(RAP_COVER_BANDS):
            row[f"cover_{name}_pct"] = float(np.nanmean(np.where(inside_s, cover[i], np.nan)))
        forage = biomass[0] + biomass[1]
        for i, name in enumerate(RAP_BIOMASS_BANDS):
            row[f"forage_{name}_lbs_ac"] = float(np.nanmean(np.where(inside_s, biomass[i], np.nan)))
        row["forage_total_lbs_ac"] = row["forage_annual_grass_forb_lbs_ac"] + row["forage_perennial_grass_forb_lbs_ac"]
        rows.append(row)
        forage_stack[y] = forage
        annual_stack[y] = cover[0]
        log.info("RAP %s done", y)

    missing = sorted(set(years) - set(forage_stack))
    if missing:
        raise RuntimeError(f"Incomplete RAP history; missing years: {missing}")
    if len(rows) < 15:
        raise RuntimeError("At least 15 years are required for nonoverlapping 10/5-year comparisons")
    series = pd.DataFrame(rows)
    series.to_csv(PROCESSED / "rap_annual.csv", index=False)

    # Forage anomaly: latest year vs the 1991-2020 normal (or all years if shorter)
    normal_years = [y for y in forage_stack if 1991 <= y <= 2020]
    if len(normal_years) != 30:
        raise ValueError("The 1991–2020 normal requires all 30 years")
    normal = np.nanmean(np.stack([forage_stack[y] for y in normal_years]), axis=0)
    y_last = max(forage_stack)
    with np.errstate(divide="ignore", invalid="ignore"):
        anomaly = 100.0 * (forage_stack[y_last] - normal) / normal
    write_tif(PROCESSED / "rap_forage_anomaly.tif", np.where(inside_s, anomaly, np.nan), t_s)

    # Annual grass change: recent 5 years minus the first 10 years on record
    first10 = sorted(annual_stack)[:10]
    last5 = sorted(annual_stack)[-5:]
    change = (np.nanmean(np.stack([annual_stack[y] for y in last5]), axis=0)
              - np.nanmean(np.stack([annual_stack[y] for y in first10]), axis=0))
    write_tif(PROCESSED / "rap_annual_change.tif", np.where(inside_s, change, np.nan), t_s)

    # 2. Detailed maps for the latest year
    t_m, shape_m, _ = make_grid(bounds, rap["map_resolution_m"])
    inside_m = area_mask(area, t_m, shape_m) & grazing_mask(site, bounds, shape_m, manifest)
    cover = _read_rap("vegetation-cover", y_last, 6, bounds, shape_m)
    biomass = _read_rap("vegetation-biomass", y_last, 2, bounds, shape_m)
    if cover is None or biomass is None:
        raise RuntimeError("Latest-year detailed RAP maps could not be read")
    write_tif(PROCESSED / "rap_perennial_cover.tif", np.where(inside_m, cover[3], np.nan), t_m)
    write_tif(PROCESSED / "rap_annual_cover.tif", np.where(inside_m, cover[0], np.nan), t_m)
    write_tif(PROCESSED / "rap_forage.tif", np.where(inside_m, biomass[0] + biomass[1], np.nan), t_m)

    record(manifest, "rap", status="ok",
           source="Rangeland Analysis Platform v3 (USDA-NRCS, BLM, Univ. of Montana)",
           url="https://rangelands.app/",
           note=f"Years {min(forage_stack)}-{y_last}; normal = {min(normal_years)}-{max(normal_years)}; fixed {site['landcover']['year']} grassland/shrubland mask; minimum valid coverage 90%",
           files=["rap_annual.csv", "rap_perennial_cover.tif", "rap_annual_cover.tif", "rap_forage.tif",
                  "rap_forage_anomaly.tif", "rap_annual_change.tif"])
    manifest["latest_rap_year"] = y_last


# Drought

def _find(cols, *names):
    low = {c.lower(): c for c in cols}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def build_drought(site: dict, manifest: dict, start_year: int = 2000) -> None:
    """Weekly share of each county in each drought category (not cumulative).

    Writes drought_weekly.csv with columns: date, county, none, d0, d1, d2, d3, d4
    """
    frames = []
    end = date.today()
    for fips, name in site["drought_counties"].items():
        params = {"aoi": fips, "startdate": f"1/1/{start_year}",
                  "enddate": f"{end.month}/{end.day}/{end.year}", "statisticsType": 2}
        r = requests.get(USDM_COUNTY, params=params, timeout=180, headers={"Accept": "text/csv"})
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        date_col = _find(df.columns, "MapDate", "ValidStart", "Date")
        if date_col is None:
            raise ValueError("Drought CSV has no date column")
        out = pd.DataFrame({"date": pd.to_datetime(df[date_col].astype(str), errors="coerce")})
        for cat in ["None", "D0", "D1", "D2", "D3", "D4"]:
            col = _find(df.columns, cat)
            if col is None:
                raise ValueError(f"Drought CSV missing category {cat}")
            out[cat.lower()] = pd.to_numeric(df[col], errors="coerce")
        out["county"] = name
        from .validation import validate_drought
        validate_drought(out)
        if (out.date.max() - out.date.min()).days < 365:
            raise ValueError("At least one year of drought history is required")
        frames.append(out)
    weekly = pd.concat(frames).sort_values(["county", "date"])
    weekly.to_csv(PROCESSED / "drought_weekly.csv", index=False)
    record(manifest, "drought", status="ok",
           source="U.S. Drought Monitor (NDMC, USDA, NOAA), county statistics",
           url="https://droughtmonitor.unl.edu/", note=", ".join(site["drought_counties"].values()),
           files=["drought_weekly.csv"])


# ArcGIS feature services (water and fire)

def _arcgis_query(url: str, bounds, where: str = "1=1", generalize_deg: float | None = None,
                  page: int = 250) -> gpd.GeoDataFrame:
    """Page through an ArcGIS REST query for every feature touching `bounds`."""
    frames, offset = [], 0
    while True:
        params = {
            "where": where, "outFields": "*", "f": "geojson", "returnGeometry": "true",
            "geometry": ",".join(str(b) for b in bounds), "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects", "inSR": "4326", "outSR": "4326",
            "resultOffset": offset, "resultRecordCount": page,
        }
        if generalize_deg:
            params["maxAllowableOffset"] = generalize_deg
        r = requests.get(url, params=params, timeout=300)
        r.raise_for_status()
        payload = r.json()
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        feats = payload.get("features", [])
        if not feats:
            break
        frames.append(gpd.GeoDataFrame.from_features(feats, crs=CRS_GEO))
        if len(feats) < page and not payload.get("exceededTransferLimit"):
            break
        offset += len(feats)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=CRS_GEO)
    return pd.concat(frames, ignore_index=True)


def build_water(site: dict, area: gpd.GeoDataFrame, manifest: dict) -> None:
    """Mapped surface water and a distance-to-water surface.

    Distance is measured to perennial streams and to mapped ponds, stock dams,
    and reservoirs. Wells and stock tanks are not in public data, which is
    exactly the kind of local knowledge a range team would add.
    """
    bounds = tuple(area.total_bounds)
    flow = _arcgis_query(NHD_FLOWLINES, bounds, where="FCode = 46006", generalize_deg=0.0003)
    bodies = _arcgis_query(NHD_WATERBODIES, bounds, generalize_deg=0.0003)

    fcode = _find(flow.columns, "FCode", "FCODE")
    if len(flow) and not set(flow.geom_type).issubset({"LineString", "MultiLineString"}):
        raise ValueError("Flowline service returned unexpected geometry")
    if len(bodies) and not set(bodies.geom_type).issubset({"Polygon", "MultiPolygon"}):
        raise ValueError("Waterbody service must return polygons")
    if len(flow) and not fcode:
        raise ValueError("Flowline service lacks FCode; refusing to include seasonal streams")
    perennial = flow[pd.to_numeric(flow[fcode], errors="coerce").isin(PERENNIAL_FCODES)] if fcode else flow
    perennial = gpd.clip(perennial[["geometry"]], area)
    bodies = gpd.clip(bodies[["geometry"]], area)
    perennial.to_file(PROCESSED / "water_streams.geojson", driver="GeoJSON")
    bodies.to_file(PROCESSED / "water_bodies.geojson", driver="GeoJSON")

    res = site["rap"]["map_resolution_m"]
    t, shape, (dy, dx) = make_grid(bounds, res)
    shapes = [(g, 1) for g in list(perennial.geometry) + list(bodies.geometry) if g is not None]
    if not shapes:
        raise ValueError("No mapped water in study area; distance is undefined")
    water = rasterize(shapes, out_shape=shape, transform=t, fill=0, all_touched=True).astype(bool)
    # distance_transform_edt measures distance to the nearest zero, so invert the water mask.
    # `sampling` gives the real pixel height and width in meters.
    if not water.any():
        raise ValueError("No water intersects the distance grid")
    dist_km = distance_transform_edt(~water, sampling=(dy, dx)) / 1000.0
    write_tif(PROCESSED / "water_distance_km.tif",
              np.where(area_mask(area, t, shape), dist_km, np.nan), t)
    record(manifest, "water", status="ok", source="USGS NHDPlus High Resolution",
           url="https://www.usgs.gov/national-hydrography/nhdplus-high-resolution",
           note=f"{len(perennial):,} perennial stream segments; {len(bodies):,} ponds, reservoirs, and lakes",
           files=["water_streams.geojson", "water_bodies.geojson", "water_distance_km.tif"])


def build_fire(area: gpd.GeoDataFrame, manifest: dict) -> None:
    """Past fire perimeters (all years the service holds) inside the area."""
    fires = _arcgis_query(NIFC_FIRES, tuple(area.total_bounds), generalize_deg=0.0003)
    keep = {}
    for want, names in {"year": ("FIRE_YEAR", "FIRE_YEAR_INT"), "name": ("INCIDENT", "FIRE_NAME"),
                        "acres": ("GIS_ACRES",)}.items():
        col = _find(fires.columns, *names)
        if col:
            keep[col] = want
    fires = fires[list(keep) + ["geometry"]].rename(columns=keep)
    fires = gpd.clip(fires, area)
    fires["year"] = pd.to_numeric(fires.get("year", pd.Series(index=fires.index, dtype=float)), errors="coerce")
    if "name" not in fires:
        fires["name"] = "Unnamed"
    fires["acres_in_area"] = fires.to_crs(CRS_AREA).area / 4046.86
    fires.to_file(PROCESSED / "fire_perimeters.geojson", driver="GeoJSON")
    record(manifest, "fire", status="ok", source="NIFC InterAgency Fire Perimeter History",
           url="https://data-nifc.opendata.arcgis.com/", note=f"{len(fires):,} mapped fires",
           files=["fire_perimeters.geojson"])

