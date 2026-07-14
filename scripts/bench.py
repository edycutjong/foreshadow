#!/usr/bin/env python3
"""Print the Foreshadow bench: per-surface latency/cost + $2/$4/$8 budget
sweep, as a markdown table (BUILD_PLAN.md mandatory deliverable).

Usage: python scripts/bench.py   (equivalent to `foreshadow bench`)
"""

from foreshadow.bench import bench_report

if __name__ == "__main__":
    print(bench_report())
