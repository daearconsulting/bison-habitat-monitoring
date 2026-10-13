"""Validate all publication prerequisites; fail closed."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sitekit.validation import validate
parser = argparse.ArgumentParser()
parser.add_argument("--allow-demo", action="store_true", help="local preview validation only")
args = parser.parse_args()
try:
    validate(allow_demo=args.allow_demo)
except Exception as exc:
    sys.exit(f"Data validation failed: {exc}")
print("Data check passed.")
