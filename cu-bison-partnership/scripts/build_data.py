"""Build the data products the website shows.

Usage (from the project folder, with the environment active):

    python scripts/build_data.py           # real public data (needs internet; a few minutes)
    python scripts/build_data.py --demo    # made-up preview data, for checking layout only
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sitekit import fetch  # noqa: E402
from sitekit.config import PROCESSED, load_site, record, write_manifest  # noqa: E402
from sitekit.config import has_demo
from sitekit.demo import build_demo  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="write synthetic preview data instead")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    site = load_site()
    manifest = {"datasets": {}}

    if args.demo:
        build_demo(site, manifest)
        write_manifest(manifest)
        print("Preview data written. Do not publish a preview build.")
        return 0

    manifest["mode"] = "real"
    area = fetch.build_area(site, manifest)
    try:
        fetch.build_grassland(site, area, manifest)
        print("grassland: ok")
    except Exception as exc:
        record(manifest, "rap", status="failed", source="Rangeland Analysis Platform", url="https://rangelands.app/",
               note=f"{type(exc).__name__}: {exc}")
        print(f"grassland: FAILED ({exc})")
    write_manifest(manifest)
    print(f"Outputs are in {PROCESSED}")
    return 1 if any(d["status"] == "failed" for d in manifest["datasets"].values()) else 0


if __name__ == "__main__":
    from sitekit.transaction import run
    raise SystemExit(run(main))
