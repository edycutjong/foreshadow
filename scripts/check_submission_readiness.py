#!/usr/bin/env python3
"""Submission gate (BUILD_PLAN.md mandatory deliverable).

Fails (exit 1) on any of:
  - missing LICENSE (or a LICENSE that is not MIT)
  - missing README.md, or README missing a required section
  - README not opening with the hero <img> embed, or a missing hero asset
  - missing mandated deliverables (DEMO, BENCH, friction log, infra/fc, scripts)
  - placeholder text (TODO / FIXME / TKTK / lorem ipsum / ...) in any doc

Prints one PASS/FAIL line per check. Exit 0 = ready to submit.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs"

PLACEHOLDER_TOKENS = (
    "TODO", "FIXME", "TKTK", "XXX", "PLACEHOLDER", "REPLACE_ME",
    "lorem ipsum", "coming soon", "<insert", "FILL ME",
)

REQUIRED_README_SECTIONS = (
    "quickstart",       # judge run instructions
    "why only qwen",    # the sponsor-defense (WHY-QWEN) section
    "status",           # honest stub / pending list
    "test",             # test count callout
    "replay",           # zero-key judge path
)

REQUIRED_FILES = (
    "README.md",
    "DEMO.md",
    "LICENSE",
    "pyproject.toml",
    "docs/BENCH.md",
    "docs/friction-log.md",
    "scripts/bench.py",
    "scripts/verify_offline.py",
    "infra/fc/handler.py",
    "infra/fc/s.yaml",
    "infra/fc/PROOF.md",
)

DOCS_TO_SCAN = (
    "README.md", "DEMO.md", "docs/BENCH.md", "docs/friction-log.md",
    "docs/SPEC-PROVENANCE.md", "infra/fc/PROOF.md",
)


class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}{'  — ' + detail if detail else ''}")
        if not ok:
            self.failures += 1
        return ok


def main() -> int:
    c = Checker()

    # -- required files exist --------------------------------------------------
    for rel in REQUIRED_FILES:
        c.check(f"exists: {rel}", (ROOT / rel).exists())

    # -- LICENSE is MIT --------------------------------------------------------
    lic = ROOT / "LICENSE"
    c.check("LICENSE is MIT", lic.exists() and "MIT" in lic.read_text(encoding="utf-8"))

    # -- README structure ------------------------------------------------------
    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        lower = text.lower()
        first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
        c.check(
            "README opens with icon + hero <img> embeds",
            first_line.strip().startswith('<div align="center">')
            and "docs/icon.svg" in text[:800]
            and "docs/readme-hero.svg" in text[:800],
            first_line[:60],
        )
        c.check(
            "hero + icon assets present",
            (ASSETS / "readme-hero.svg").exists() and (ASSETS / "icon.svg").exists(),
            str(ASSETS / "readme-hero.svg"),
        )
        for section in REQUIRED_README_SECTIONS:
            c.check(f"README section: '{section}'", section in lower)
    else:
        c.check("README.md exists", False)

    # -- DEMO mentions the zero-key replay path --------------------------------
    demo = ROOT / "DEMO.md"
    if demo.exists():
        c.check("DEMO documents replay", "replay" in demo.read_text(encoding="utf-8").lower())

    # -- no placeholder text in any doc ----------------------------------------
    for rel in DOCS_TO_SCAN:
        path = ROOT / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        hits = [tok for tok in PLACEHOLDER_TOKENS if tok.lower() in content.lower()]
        c.check(f"no placeholders in {rel}", not hits, ", ".join(hits))

    print()
    if c.failures:
        print(f"NOT READY — {c.failures} check(s) failed")
        return 1
    print("SUBMISSION READY — all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
