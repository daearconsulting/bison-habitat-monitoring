import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from rasterio.transform import array_bounds
from sitekit.config import has_demo
from sitekit.fetch import make_grid
from sitekit.validation import validate, validate_drought

class RegressionTests(unittest.TestCase):
    def test_grid_preserves_requested_extent(self):
        bounds = (-105.6, 39.4, -104.5, 41.0)
        transform, shape, spacing = make_grid(bounds, 90)
        np.testing.assert_allclose(array_bounds(*shape, transform), bounds, atol=1e-10)
        self.assertTrue(all(x > 0 for x in spacing))

    def test_mixed_provenance_is_demo(self):
        m = {"mode": "real", "datasets": {"rap": {"status": "demo"}}}
        self.assertTrue(has_demo(m))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "Synthetic"):
                validate(p)

    def test_empty_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "manifest.json").write_text("{}")
            with self.assertRaises(ValueError): validate(p)

    def test_success_without_files_rejected(self):
        from datetime import datetime, timezone
        m = {"mode":"real", "datasets":{"area":{"status":"ok", "files":[], "retrieved_utc":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")}}}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p / "manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "output files"): validate(p)

    def test_cumulative_or_missing_drought_rejected(self):
        frame=pd.DataFrame({"date":["2025-01-01"],"county":["A"],"none":[0],"d0":[100],"d1":[50],"d2":[20],"d3":[0],"d4":[0]})
        with self.assertRaises(ValueError): validate_drought(frame)
        frame["d0"]=30
        validate_drought(frame)
        with self.assertRaises(ValueError): validate_drought(frame.drop(columns="d4"))

    def test_printable_raster_map(self):
        from sitekit import show
        import folium
        import geopandas as gpd
        from shapely.geometry import box
        with patch.object(show, "area", return_value=gpd.GeoDataFrame(geometry=[box(-101,43,-100,44)], crs="EPSG:4326")):
            m=folium.Map()
            folium.raster_layers.ImageOverlay(show._png(np.ones((3,3)),"YlGn",0,2), bounds=[[43,-101],[44,-100]],opacity=0.7).add_to(m)
            self.assertIn("data:image/png;base64", show.static_map(m))

    def test_failed_refresh_keeps_previous_data(self):
        from sitekit import transaction
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            processed=root/"data"/"processed"
            processed.mkdir(parents=True)
            (processed/"sentinel").write_text("known working")
            with patch.object(transaction,"ROOT",root), patch.object(transaction,"PROCESSED",processed), patch.dict("os.environ", {}, clear=True), patch("sys.argv", ["build_data.py"]), patch.object(transaction.subprocess,"run") as run:
                run.return_value.returncode=1
                self.assertEqual(transaction.run(lambda: 0),1)
            self.assertEqual((processed/"sentinel").read_text(),"known working")

if __name__ == "__main__": unittest.main()


class WaterAndFireTests(unittest.TestCase):
    def test_wrong_waterbody_geometry_is_rejected(self):
        import geopandas as gpd
        from shapely.geometry import box, LineString
        from sitekit import fetch
        area=gpd.GeoDataFrame(geometry=[box(-101,43,-100,44)],crs="EPSG:4326")
        lines=gpd.GeoDataFrame({"FCode":[46006]},geometry=[LineString([(-100.9,43.1),(-100.8,43.2)])],crs="EPSG:4326")
        with patch.object(fetch,"_arcgis_query",return_value=lines):
            with self.assertRaisesRegex(ValueError,"polygons"):
                fetch.build_water({"rap":{"map_resolution_m":90}},area,{})

    def test_null_fire_years_can_be_grouped(self):
        frame=pd.DataFrame({"year":[2020,None],"acres_in_area":[10,20]})
        from sitekit.show import fire_year_totals
        self.assertEqual(fire_year_totals(frame).loc[2020],10)
