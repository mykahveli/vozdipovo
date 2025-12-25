#!filepath: src/vozdipovo_app/utils/serialization.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Structured result for config file loads.

    Args:
        data: Parsed payload when successful.
        path: File path attempted.
        ok: Whether parsing succeeded.
    """

    data: dict[str, Any]
    path: Path
    ok: bool


def load_yaml_dict(path: Path) -> LoadResult:
    """Load a YAML file and return a dictionary payload.

    Args:
        path: Path to a YAML file.

    Returns:
        LoadResult: Parsed data and status.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error(f"Falha ao ler YAML em {path}: {exc}")
        return LoadResult(data={}, path=path, ok=False)

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        logger.error(f"Falha ao fazer parse do YAML em {path}: {exc}")
        return LoadResult(data={}, path=path, ok=False)

    if raw is None:
        return LoadResult(data={}, path=path, ok=True)

    if not isinstance(raw, Mapping):
        logger.error(
            f"YAML inválido em {path}, esperado objeto, recebido {type(raw).__name__}"
        )
        return LoadResult(data={}, path=path, ok=False)

    return LoadResult(data=dict(raw), path=path, ok=True)


def load_json_dict(path: Path) -> LoadResult:
    """Load a JSON file and return a dictionary payload.

    Args:
        path: Path to a JSON file.

    Returns:
        LoadResult: Parsed data and status.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error(f"Falha ao ler JSON em {path}: {exc}")
        return LoadResult(data={}, path=path, ok=False)

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(f"Falha ao fazer parse do JSON em {path}: {exc}")
        return LoadResult(data={}, path=path, ok=False)

    if raw is None:
        return LoadResult(data={}, path=path, ok=True)

    if not isinstance(raw, Mapping):
        logger.error(
            f"JSON inválido em {path}, esperado objeto, recebido {type(raw).__name__}"
        )
        return LoadResult(data={}, path=path, ok=False)

    return LoadResult(data=dict(raw), path=path, ok=True)
