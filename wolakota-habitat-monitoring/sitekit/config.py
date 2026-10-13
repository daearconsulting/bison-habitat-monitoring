"""Paths and site settings shared by every module."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
import os
PROCESSED = Path(os.environ.get("SITEKIT_PROCESSED", ROOT / "data" / "processed"))
CACHE = ROOT / "data" / "cache"
MANIFEST = PROCESSED / "manifest.json"

# Equal-area projection for anything measured in acres or meters.
CRS_GEO = "EPSG:4326"
CRS_AREA = "EPSG:5070"


def load_site() -> dict:
    """Read site.yaml (the one place where place-specific settings live)."""
    with open(ROOT / "site.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"mode": "missing", "datasets": {}}


def record(manifest: dict, key: str, *, status: str, source: str, url: str,
           note: str = "", files: list[str] | None = None) -> None:
    """Add one dataset's provenance to the manifest.

    Every product on the site carries where it came from, when it was
    retrieved, and whether the retrieval worked. The 'Data and governance'
    page prints this table so readers can see the provenance of each map.
    """
    manifest.setdefault("datasets", {})[key] = {
        "status": status,            # "ok", "failed", or "demo"
        "source": source,
        "url": url,
        "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "note": note,
        "files": files or [],
    }


def write_manifest(manifest: dict) -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def has_demo(manifest):
    return manifest.get("mode") == "demo" or any(
        d.get("status") == "demo" for d in manifest.get("datasets", {}).values())
