#!/usr/bin/env python3
"""Regenerate fixtures/cache/ — the committed replay artifacts.

Runs the deterministic replay for each seed incident at its demo budget
(forklift@$4, ladder@$2, chemical@$4) and copies the job directory into
fixtures/cache/<incident>/. Because the fake pipeline is byte-deterministic,
re-running this script produces an identical tree; tests + verify_offline.py
compare fresh replays against it.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from foreshadow import config
from foreshadow.pipeline.engine import replay

DEMO_BUDGETS = {"forklift": 4.0, "ladder": 2.0, "chemical": 4.0}


def main() -> int:
    cache_root = config.fixtures_dir() / "cache"
    with tempfile.TemporaryDirectory(prefix="foreshadow-cache-") as tmp:
        for incident_id, budget in DEMO_BUDGETS.items():
            result, _ = replay(incident_id, budget, home=Path(tmp) / incident_id)
            dest = cache_root / incident_id
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(result.job_dir, dest)
            print(f"cached {incident_id}@${budget:g}: {result.merkle_root} -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
