"""Config: the verified Qwen model allow-list, pricing, allocator constants."""

from __future__ import annotations

from pathlib import Path

from foreshadow import config

# The ONLY model ids this project is allowed to reference (task constraint).
VERIFIED_MODELS = {
    "qwen3.7-max",
    "qwen3.7-plus",
    "qwen3.6-flash",
    "qwen3-vl-plus",
    "qwen-image-2.0-pro",
    "wan2.7-i2v",
    "wan2.6-i2v",
    "wan2.6-i2v-flash",
    "cosyvoice-v3-plus",
}


def test_allowed_models_is_exactly_the_verified_set():
    assert set(config.ALLOWED_MODELS) == VERIFIED_MODELS


def test_allowed_models_is_frozenset():
    assert isinstance(config.ALLOWED_MODELS, frozenset)


def test_every_model_constant_is_allowed():
    for name in dir(config):
        if name.startswith("MODEL_"):
            assert getattr(config, name) in config.ALLOWED_MODELS, name


def test_no_forbidden_model_ids_present():
    forbidden = {"gpt-4", "gpt-4o", "claude", "gemini", "qwen-max", "qwen3.5"}
    assert forbidden.isdisjoint(config.ALLOWED_MODELS)


def test_screenplay_and_shotplan_share_the_max_model():
    assert config.MODEL_SCREENPLAY == "qwen3.7-max"
    assert config.MODEL_SHOTPLAN == config.MODEL_SCREENPLAY


def test_dashscope_base_url_is_intl():
    assert config.DASHSCOPE_BASE_URL.startswith("https://dashscope-intl")


def test_quality_factor_ladder():
    assert config.QUALITY_FACTOR == {"hero": 1.0, "connective": 0.6, "kenburns": 0.3}


def test_spend_fractions_ordered():
    assert 0 < config.HERO_SPEND_FRACTION < config.TOTAL_SPEND_FRACTION < 1


def test_kill_switch_multiplier():
    assert config.KILL_SWITCH_MULTIPLIER == 2.5


def test_tier_weight_thresholds():
    assert config.HERO_MIN_WEIGHT == 7
    assert config.CONNECTIVE_MIN_WEIGHT == 4


def test_pricing_two_render_tiers():
    assert config.COST_HERO_PER_S > config.COST_CONNECTIVE_PER_S > 0
    assert config.COST_KENBURNS == 0.0


def test_batch_discount_is_half():
    assert config.BATCH_DISCOUNT == 0.5


def test_default_budget_and_retries():
    assert config.DEFAULT_BUDGET_USD == 4.0
    assert config.MAX_QC_RETRIES == 1


def test_incident_ids():
    assert config.INCIDENT_IDS == ("forklift", "ladder", "chemical")


def test_home_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FORESHADOW_HOME", str(tmp_path / "h"))
    assert config.home_dir() == tmp_path / "h"


def test_db_and_jobs_dir_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("FORESHADOW_HOME", str(tmp_path))
    assert config.db_path() == tmp_path / "foreshadow.db"
    assert config.jobs_dir() == tmp_path / "jobs"


def test_seeds_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FORESHADOW_SEEDS", str(tmp_path / "s"))
    assert config.seeds_dir() == tmp_path / "s"


def test_fixtures_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FORESHADOW_FIXTURES", str(tmp_path / "fx"))
    assert config.fixtures_dir() == tmp_path / "fx"


def test_repo_root_contains_src(monkeypatch):
    assert (config.REPO_ROOT / "src" / "foreshadow").is_dir()


def test_default_seeds_dir_exists():
    assert isinstance(config.seeds_dir(), Path)
    assert (config.seeds_dir() / "forklift.txt").exists()
