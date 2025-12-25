#!filepath: tests/test_settings_load.py
from __future__ import annotations

from pathlib import Path

from vozdipovo_app.settings import load_app_config
from vozdipovo_app.utils.project_paths import ProjectPaths


def test_load_app_config_smoke() -> None:
    """Load default config and ensure expected top level keys exist."""
    paths = ProjectPaths.discover()
    cfg = load_app_config(paths)
    assert isinstance(cfg, dict)
    assert "paths" in cfg
    assert "api" in cfg
    assert "wordpress" in cfg


def test_editorial_json_exists() -> None:
    """Ensure editorial.json exists in configs."""
    paths = ProjectPaths.discover()
    p = (paths.configs_dir / "editorial.json").resolve()
    assert p.exists()
