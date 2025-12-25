#!filepath: tests/test_judge_scoring.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.judge import calculate_significance_score


def _write(p: Path, payload: dict) -> None:
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _config_with_power(power: float) -> dict:
    return {
        "version": 1,
        "pipeline": {
            "scrape_limit_per_run": 200,
            "judge_limit_per_run": 50,
            "generate_limit_per_run": 20,
            "revision_limit_per_run": 20,
            "publish_limit_per_run": 20,
            "throttle_seconds": {"judge": 0.2, "wordpress": 0.6},
        },
        "scoring": {
            "significance_threshold": 1.2,
            "significance_power": power,
            "editorial_power": 2.0,
        },
        "llm": {
            "judge": {
                "groq": {"env_override": None, "models": ["qwen/qwen3-32b"]},
                "openrouter": {"env_override": None, "models": []},
            },
            "reviser": {
                "groq": {"env_override": None, "models": ["qwen/qwen3-32b"]},
                "openrouter": {"env_override": None, "models": []},
            },
        },
        "homepage": {
            "time_window_hours": 24,
            "breaking": {"category_id": 14, "limit": 3, "editorial_threshold": 3.0},
            "featured": {"category_id": 15, "limit": 6, "editorial_threshold": 2.0},
        },
        "wordpress": {
            "default_status": "publish",
            "category_ids": {"Geral": 1, "Breaking News": 14, "Featured Stories": 15},
            "allowed_editorial_categories": ["Geral"],
        },
        "audio": {
            "enabled": True,
            "only_for_highlights": True,
            "highlights": ["BREAKING", "FEATURED"],
            "output_subdir": "audio",
        },
        "judge": {"suspend_mode": "skip"},
    }


def test_significance_power_changes_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p1 = tmp_path / "c1.json"
    p2 = tmp_path / "c2.json"
    _write(p1, _config_with_power(1.0))
    _write(p2, _config_with_power(3.0))

    scores = {
        "cv_relevance_score": 8,
        "scale_score": 8,
        "impact_score": 8,
        "novelty_score": 8,
        "potential_score": 8,
        "legacy_score": 8,
        "credibility_score": 8,
    }

    monkeypatch.setenv("EDITORIAL_CONFIG_PATH", str(p1))
    get_editorial_config(force_reload=True)
    s1 = calculate_significance_score(scores)

    monkeypatch.setenv("EDITORIAL_CONFIG_PATH", str(p2))
    get_editorial_config(force_reload=True)
    s2 = calculate_significance_score(scores)

    assert s2 < s1
