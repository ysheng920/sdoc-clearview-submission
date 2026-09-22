"""Prepare an ephemeral Cloud Run workspace, then start the web service.

The data committed in the image is immutable demo seed data. Cloud Run gives
the container a writable but ephemeral filesystem, so every instance receives
its own working copy under /tmp. This keeps Reset Demo functional without ever
modifying the baseline baked into the image.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import uvicorn


BACKEND_DIR = Path(__file__).resolve().parent
SEED_DIR = BACKEND_DIR / "data"
WORK_DIR = Path(os.environ.get("SDOC_WORK_DIR", "/tmp/sdoc-data"))


def prepare_workspace() -> None:
    if not (SEED_DIR / "demo_baseline.db").is_file():
        raise RuntimeError("backend/data/demo_baseline.db is missing from the image")

    # A new application process starts from the same known demo state. copytree
    # includes the labelled corpus, attachments, frozen simulations and mapping
    # files that the API resolves relative to SDOC_DATA_DIR.
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    shutil.copytree(SEED_DIR, WORK_DIR)
    shutil.copy2(WORK_DIR / "demo_baseline.db", WORK_DIR / "clearview.db")

    # Match the state produced by POST /api/demo/reset: the six frozen custom
    # examples live separately so user-created simulations are never committed,
    # and demo_mappings.json is the canonical clean mapping library.
    demo_simulated = WORK_DIR / "demo_simulated"
    if demo_simulated.is_dir():
        shutil.copytree(demo_simulated, WORK_DIR / "simulated", dirs_exist_ok=True)
    demo_mappings = WORK_DIR / "demo_mappings.json"
    if demo_mappings.is_file():
        shutil.copy2(demo_mappings, WORK_DIR / "mappings.json")

    # Set these before importing app.main: config.py reads them at import time.
    os.environ["SDOC_DATA_DIR"] = str(WORK_DIR)
    os.environ["SDOC_DB"] = str(WORK_DIR / "clearview.db")


def main() -> None:
    prepare_workspace()
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1)


if __name__ == "__main__":
    main()
