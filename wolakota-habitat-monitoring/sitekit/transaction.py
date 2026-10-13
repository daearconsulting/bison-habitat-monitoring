"""Build into staging; promote only validated complete outputs."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from .config import ROOT, PROCESSED
from .validation import validate

def run(main):
    if os.environ.get("SITEKIT_BUILD_CHILD"):
        return main()
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="build-", dir=data) as tmp:
        staged = Path(tmp) / "processed"
        if "--only" in sys.argv:
            validate()  # Reject demo, missing and invalid previous products before fetching.
            shutil.copytree(PROCESSED, staged)
        else:
            staged.mkdir()
        env = dict(os.environ, SITEKIT_BUILD_CHILD="1", SITEKIT_PROCESSED=str(staged))
        result = subprocess.run([sys.executable, *sys.argv], env=env)
        if result.returncode:
            return result.returncode
        # Run validation in a fresh process with the staged path.
        command = [sys.executable, str(ROOT / "scripts/check_data.py")]
        if "--demo" in sys.argv:
            command += ["--allow-demo"]
        if subprocess.run(command, env=env).returncode:
            return 1
        backup = data / "processed.previous"
        if backup.exists():
            raise RuntimeError("A previous interrupted promotion needs inspection: " + str(backup))
        if PROCESSED.exists():
            PROCESSED.rename(backup)
        try:
            staged.rename(PROCESSED)
        except Exception:
            if backup.exists():
                backup.rename(PROCESSED)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    print("Validated data promoted to " + str(PROCESSED))
    return 0
