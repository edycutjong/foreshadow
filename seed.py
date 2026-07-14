#!/usr/bin/env python3
"""Seed generator shim (SEED_DATA.md): `python seed.py --regen` rewrites
seeds/*.txt + seeds/*.json byte-identically; `python seed.py` checks them.
Requires the package to be installed (pip install -e .)."""

import sys

from foreshadow.seeds import main

if __name__ == "__main__":
    sys.exit(main())
