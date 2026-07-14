"""Central configuration: verified Qwen model IDs, pricing, allocator constants.

Every model ID used anywhere in this codebase MUST come from ALLOWED_MODELS.
Pricing mirrors SPEC.md section 5 (per-call estimates used for the ledger).
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Qwen Cloud (dashscope-intl) — the ONLY allowed model identifiers.
# ---------------------------------------------------------------------------
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"

MODEL_SCREENPLAY = "qwen3.7-max"          # screenplay w/ thinking
MODEL_SCREENPLAY_FALLBACK = "qwen3.7-plus"
MODEL_SHOTPLAN = "qwen3.7-max"            # structured-output shot list
MODEL_ALLOC = "qwen3.6-flash"             # Line Producer rationale
MODEL_IMAGE = "qwen-image-2.0-pro"        # character sheet + storyboards
MODEL_VIDEO_HERO = "wan2.7-i2v"           # hero shots
MODEL_VIDEO_HERO_FALLBACK = "wan2.6-i2v"
MODEL_VIDEO_CONNECTIVE = "wan2.6-i2v-flash"
MODEL_QC = "qwen3-vl-plus"                # dailies QC critic
MODEL_TTS = "cosyvoice-v3-plus"           # narration

ALLOWED_MODELS: frozenset[str] = frozenset(
    {
        MODEL_SCREENPLAY,
        MODEL_SCREENPLAY_FALLBACK,
        MODEL_ALLOC,
        MODEL_QC,
        MODEL_IMAGE,
        MODEL_VIDEO_HERO,
        MODEL_VIDEO_HERO_FALLBACK,
        MODEL_VIDEO_CONNECTIVE,
        MODEL_TTS,
    }
)

# ---------------------------------------------------------------------------
# Pricing (USD) — SPEC.md section 5 estimates; ledger uses these per call.
# ---------------------------------------------------------------------------
COST_SCREENPLAY = 0.10
COST_SHOTPLAN = 0.05
COST_ALLOC_RATIONALE = 0.01
COST_IMAGE = 0.075                # qwen-image-2.0-pro per image
BATCH_DISCOUNT = 0.5              # Batch API: -50% on storyboard fan-out
COST_HERO_PER_S = 0.10            # wan2.7-i2v (and wan2.6-i2v fallback) $/s
COST_CONNECTIVE_PER_S = 0.05      # wan2.6-i2v-flash $/s
COST_KENBURNS = 0.0               # ffmpeg zoompan on a storyboard frame
COST_QC_PER_REVIEW = 0.01         # qwen3-vl-plus per clip review
COST_TTS_PER_10K_CHARS = 0.26     # cosyvoice-v3-plus
COST_NARRATION_ESTIMATE = 0.03    # conservative pre-alloc estimate

# ---------------------------------------------------------------------------
# Line Producer allocator constants (SPEC.md section 6, COMPLEXITY.md section 3)
# ---------------------------------------------------------------------------
HERO_SPEND_FRACTION = 0.6         # heroes may consume <= 0.6 x render budget
TOTAL_SPEND_FRACTION = 0.9        # heroes+connective <= 0.9 x render budget
KILL_SWITCH_MULTIPLIER = 2.5      # hard stop: ledger total may never cross 2.5 x B

HERO_MIN_WEIGHT = 7               # desired tier: weight >= 7 -> hero
CONNECTIVE_MIN_WEIGHT = 4         # 4..6 -> connective; <= 3 -> ken-burns still

QUALITY_FACTOR = {"hero": 1.0, "connective": 0.6, "kenburns": 0.3}

MAX_QC_RETRIES = 1                # <=1 re-render, then demote to ken-burns

DEFAULT_BUDGET_USD = 4.0

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent  # build/ root when installed with -e


def home_dir() -> Path:
    """Runtime home (SQLite db + job artifact dirs). Overridable via env."""
    return Path(os.environ.get("FORESHADOW_HOME", Path.cwd() / "var"))


def db_path() -> Path:
    return home_dir() / "foreshadow.db"


def jobs_dir() -> Path:
    return home_dir() / "jobs"


def seeds_dir() -> Path:
    override = os.environ.get("FORESHADOW_SEEDS")
    return Path(override) if override else REPO_ROOT / "seeds"


def fixtures_dir() -> Path:
    override = os.environ.get("FORESHADOW_FIXTURES")
    return Path(override) if override else REPO_ROOT / "fixtures"


INCIDENT_IDS = ("forklift", "ladder", "chemical")
