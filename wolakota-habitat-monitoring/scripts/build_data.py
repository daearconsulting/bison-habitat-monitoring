"""Build every data product the website shows.

Usage (from the project folder, with the environment active):

    python scripts/build_data.py            # real public data (needs internet; ~10-30 min)
    python scripts/build_data.py --demo     # made-up preview data, for checking layout only
    python scripts/build_data.py --only drought water   # rebuild selected pieces

Each step is independent. If a data service is down, that step is marked
"failed" in data/processed/manifest.json and the rest still run.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geopandas as gpd  # noqa: E402

from sitekit import fetch  # noqa: E402
from sitekit.config import PROCESSED, load_site, read_manifest, record, write_manifest  # noqa: E402
from sitekit.config import has_demo
from sitekit.demo import build_demo  # noqa: E402

STEPS = ["rap", "drought", "water", "fire"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="write synthetic preview data instead")
    ap.add_argument("--only", nargs="+", choices=STEPS, help="rebuild only these steps")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    site = load_site()
    if args.demo:
        manifest = {"datasets": {}}
        build_demo(site, manifest)
        write_manifest(manifest)
        print("Preview data written. Do not publish a preview build.")
        return 0

    manifest = read_manifest() if args.only else {"datasets": {}}
    if args.only and (manifest.get("mode") != "real" or has_demo(manifest)):
        raise ValueError("Partial rebuild requires an existing complete real build; run a full rebuild first")
    manifest["mode"] = "real"
    try:
        area = fetch.build_area(site, manifest)
    except Exception as exc:
        record(manifest, "area", status="failed", source="Census", url=fetch.TIGER_AIANNH, note=str(exc))
        write_manifest(manifest)
        print(f"Could not build the study area, so nothing else can run: {exc}")
        return 1

    jobs = {
        "rap": lambda: fetch.build_rap(site, area, manifest),
        "drought": lambda: fetch.build_drought(site, manifest),
        "water": lambda: fetch.build_water(site, area, manifest),
        "fire": lambda: fetch.build_fire(area, manifest),
    }
    for name in args.only or STEPS:
        print(f"--- {name} ---")
        try:
            jobs[name]()
            print(f"{name}: ok")
        except Exception as exc:
            record(manifest, name, status="failed", source="", url="", note=f"{type(exc).__name__}: {exc}")
            print(f"{name}: FAILED ({exc})")
        write_manifest(manifest)  # save progress after every step

    failed = [k for k, v in manifest["datasets"].items() if v["status"] == "failed"]
    print("\nDone." + (f" Failed: {', '.join(failed)}" if failed else " All steps succeeded."))
    print(f"Outputs are in {PROCESSED}")
    return 1 if failed else 0


if __name__ == "__main__":
    from sitekit.transaction import run
    raise SystemExit(run(main))
