"""Publication contract: usable, current, real data only."""
from datetime import datetime, timezone
from pathlib import Path
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from .config import PROCESSED, load_site, has_demo

def validate(directory=PROCESSED, allow_demo=False):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    demo = has_demo(manifest)
    if demo and not allow_demo:
        raise ValueError("Synthetic data cannot be published, including mixed real/demo builds")
    if manifest.get("mode") not in ({"real", "demo"} if allow_demo else {"real"}):
        raise ValueError("Manifest must declare a valid build mode")
    site = load_site()
    expected = site["validation"]["required_datasets"]
    datasets = manifest.get("datasets", {})
    products = {"area": {"area.geojson"}, "landcover": {"rangeland_mask.tif"}}
    if "drought" in expected:
        products.update(rap={"rap_annual.csv", "rap_perennial_cover.tif", "rap_annual_cover.tif", "rap_forage.tif", "rap_forage_anomaly.tif", "rap_annual_change.tif"},
                        drought={"drought_weekly.csv"}, water={"water_streams.geojson", "water_bodies.geojson", "water_distance_km.tif"}, fire={"fire_perimeters.geojson"})
    else:
        products["rap"] = {"rap_perennial_cover.tif", "rap_tree_cover.tif", "open_grassland.tif", "grassland_blocks.geojson"}
    for key in expected:
        entry = datasets.get(key, {})
        if entry.get("status") not in ({"ok", "demo"} if allow_demo else {"ok"}):
            raise ValueError(f"Required dataset {key} is missing or failed")
        stamp = datetime.strptime(entry["retrieved_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds() / 86400
        if not demo and (age < -1 or age > site["validation"]["max_age_days"].get(key, 400)):
            raise ValueError(f"Dataset {key} needs refreshing (age {age:.0f} days)")
        files = entry.get("files", [])
        if not files:
            raise ValueError(f"Dataset {key} must list its output files")
        if not products[key].issubset(files):
            raise ValueError(f"Dataset {key} omits required output files")
        for name in files:
            path = (directory / name).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file():
                raise ValueError(f"Missing or invalid dataset path: {name}")
            if path.suffix == ".tif":
                with rasterio.open(path) as src:
                    values = src.read(1, masked=True).compressed()
                    # A zero-block CU screen legitimately has an empty mask.
                    if src.crs is None or not src.transform.a > 0:
                        raise ValueError(f"Invalid raster georeferencing: {name}")
                    if name != "open_grassland.tif" and (not len(values) or not np.isfinite(values).all()):
                        raise ValueError(f"Raster has no usable values: {name}")
            elif path.suffix == ".geojson":
                frame = gpd.read_file(path)
                if frame.crs is None or (len(frame) and not frame.geometry.is_valid.all()):
                    raise ValueError(f"Invalid geometry: {name}")
                if name == "area.geojson" and (frame.empty or "acres" not in frame or frame.acres.sum() <= 0):
                    raise ValueError("Study area is empty or lacks acreage")
    if "rap" in expected and (directory / "rap_annual.csv").exists():
        df = pd.read_csv(directory / "rap_annual.csv")
        cols = ["year", "forage_total_lbs_ac", "cover_annual_grass_forb_pct", "cover_perennial_grass_forb_pct"]
        if not set(cols).issubset(df.columns) or len(df) < 15 or df.year.duplicated().any():
            raise ValueError("RAP history needs at least 15 unique years and required columns")
        if not np.isfinite(df[cols].to_numpy()).all() or (df.forage_total_lbs_ac < 0).any():
            raise ValueError("RAP history contains invalid observations")
    if "drought" in expected:
        df = pd.read_csv(directory / "drought_weekly.csv")
        validate_drought(df)
        if not demo and (pd.Timestamp.now().normalize() - pd.to_datetime(df.date).max()).days > 21:
            raise ValueError("Drought observations are older than 21 days")
    return manifest

def validate_drought(df):
    cols = ["none", "d0", "d1", "d2", "d3", "d4"]
    if df.empty or not set(["date", "county", *cols]).issubset(df.columns):
        raise ValueError("Drought response lacks dates, counties, or categories")
    values = df[cols].to_numpy(dtype=float)
    dates = pd.to_datetime(df.date, errors="coerce")
    if dates.isna().any() or not np.isfinite(values).all() or (values < 0).any() or (values > 100).any():
        raise ValueError("Invalid drought dates or percentages")
    if not np.allclose(values.sum(axis=1), 100, atol=0.2):
        raise ValueError("Drought categories must be exclusive and sum to 100%")
    if df.duplicated(["date", "county"]).any():
        raise ValueError("Duplicate county/week drought observations")
