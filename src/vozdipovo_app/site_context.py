#!filepath: src/vozdipovo_app/site_context.py
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from vozdipovo_app.utils.serialization import load_yaml_dict


@dataclass(frozen=True, slots=True)
class SiteContext:
    """Resolved editorial context for a source site."""

    site_name: str
    default_country: str = ""


def _candidate_sites_paths(project_root: Optional[Path] = None) -> list[Path]:
    root = (project_root or Path.cwd()).resolve()
    return [
        (root / "configs" / "sites.yaml").resolve(),
        (root / "sites.yaml").resolve(),
    ]


@lru_cache(maxsize=1)
def _load_sites_yaml(project_root_str: str) -> dict[str, dict[str, Any]]:
    root = Path(project_root_str).resolve()
    sites_path = next((p for p in _candidate_sites_paths(root) if p.exists()), None)
    if not sites_path:
        return {}

    res = load_yaml_dict(sites_path)
    if not res.ok:
        return {}

    sites = res.data.get("sites", [])
    if not isinstance(sites, list):
        return {}

    by_name: dict[str, dict[str, Any]] = {}

    for item in sites:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or "").strip()
        if not name:
            continue

        cfg = item.get("config") if isinstance(item.get("config"), dict) else {}
        by_name[name] = cfg

    return by_name


def resolve_site_context(
    site_name: str, project_root: Optional[Path] = None
) -> SiteContext:
    """Resolve site context from configs/sites.yaml.

    Args:
        site_name: Value stored in legal_docs.site_name.
        project_root: Project root directory.

    Returns:
        SiteContext: Resolved context.
    """
    root = (project_root or Path.cwd()).resolve()
    cfg_by_name = _load_sites_yaml(str(root))
    cfg = cfg_by_name.get(site_name, {})
    default_country = str(cfg.get("default_country") or "").strip()
    return SiteContext(site_name=site_name, default_country=default_country)
