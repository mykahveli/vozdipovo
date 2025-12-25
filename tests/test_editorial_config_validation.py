#!filepath: tests/test_editorial_config_validation.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vozdipovo_app.editorial.config import (
    get_editorial_config,
    load_editorial_config_from_path,
)


def _write(p: Path, payload: dict) -> None:
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _base_config() -> dict:
    return {
        "version": 1,
        "pipeline": {
            "scrape_limit_per_run": 300,
            "judge_limit_per_run": 120,
            "generate_limit_per_run": 30,
            "revision_limit_per_run": 30,
            "publish_limit_per_run": 25,
            "throttle_seconds": {"judge": 0.2, "wordpress": 0.6},
        },
        "scoring": {
            "significance_threshold": 1.2,
            "significance_power": 1.8,
            "editorial_power": 2.0,
        },
        "llm": {
            "judge": {
                "groq": {
                    "env_override": "JUDGE_GROQ_MODELS",
                    "models": ["llama-3.3-70b-versatile", "qwen/qwen3-32b"],
                },
                "openrouter": {
                    "env_override": "JUDGE_OPENROUTER_MODELS",
                    "models": ["meta-llama/llama-3.3-70b-instruct:free"],
                },
            },
            "reviser": {
                "groq": {
                    "env_override": "REVISER_GROQ_MODELS",
                    "models": ["qwen/qwen3-32b"],
                },
                "openrouter": {
                    "env_override": "REVISER_OPENROUTER_MODELS",
                    "models": ["meta-llama/llama-3.3-70b-instruct:free"],
                },
            },
        },
        "homepage": {
            "time_window_hours": 24,
            "breaking": {"category_id": 14, "limit": 3, "editorial_threshold": 3.0},
            "featured": {"category_id": 15, "limit": 6, "editorial_threshold": 2.0},
        },
        "wordpress": {
            "default_status": "publish",
            "category_ids": {
                "Geral": 1,
                "Economia": 13,
                "Breaking News": 14,
                "Featured Stories": 15,
            },
            "allowed_editorial_categories": ["Economia", "Geral"],
        },
        "audio": {
            "enabled": True,
            "only_for_highlights": True,
            "highlights": ["BREAKING", "FEATURED"],
            "output_subdir": "audio",
        },
        "judge": {"suspend_mode": "skip"},
    }


def test_load_editorial_config_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "editorial.json"
    _write(p, _base_config())
    cfg = load_editorial_config_from_path(p)
    assert cfg.version == 1
    assert cfg.pipeline.generate_limit_per_run == 30


def test_unknown_key_rejected(tmp_path: Path) -> None:
    p = tmp_path / "editorial.json"
    payload = _base_config()
    payload["unexpected"] = 123
    _write(p, payload)
    with pytest.raises(Exception):
        load_editorial_config_from_path(p)


def test_get_editorial_config_env_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "editorial.json"
    _write(p, _base_config())
    monkeypatch.setenv("EDITORIAL_CONFIG_PATH", str(p))
    cfg = get_editorial_config(force_reload=True)
    assert cfg.pipeline.judge_limit_per_run == 120
