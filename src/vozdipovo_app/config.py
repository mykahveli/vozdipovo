#!src/vozdipovo_app/editorial/config.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from vozdipovo_app.editorial.models import EditorialConfig, ModelPool
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import yaml
except Exception:
    yaml = None


class EditorialConfigError(RuntimeError):
    """Erro ao carregar ou validar config editorial."""


def _strip_private_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_private_keys(v)
            for k, v in obj.items()
            if not str(k).startswith("__")
        }
    if isinstance(obj, list):
        return [_strip_private_keys(x) for x in obj]
    return obj


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf_8")
    except OSError as e:
        raise EditorialConfigError(f"Falha ao ler config em {path}: {e}") from e


def _parse_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise EditorialConfigError(f"JSON inválido: {e}") from e
    if not isinstance(data, dict):
        raise EditorialConfigError("Config JSON inválido, esperado objeto no topo")
    return data


def _parse_yaml(text: str) -> dict[str, Any]:
    if yaml is None:
        raise EditorialConfigError("Suporte YAML indisponível, instala PyYAML")
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise EditorialConfigError(f"YAML inválido: {e}") from e
    if not isinstance(data, dict):
        raise EditorialConfigError("Config YAML inválido, esperado mapping no topo")
    return data


def load_editorial_config_from_path(path: Path) -> EditorialConfig:
    """Carrega e valida config editorial.

    Args:
        path: Path para ficheiro json, yaml, ou yml.

    Returns:
        EditorialConfig: Config validado.

    Raises:
        EditorialConfigError: Em caso de falha.
    """
    p = path.expanduser().resolve()
    if not p.exists():
        raise EditorialConfigError(f"Editorial config não encontrado: {p}")

    text = _read_text(p)
    suffix = p.suffix.lower()

    if suffix == ".json":
        data = _parse_json(text)
    elif suffix in {".yaml", ".yml"}:
        data = _parse_yaml(text)
    else:
        raise EditorialConfigError("Formato não suportado, usa json, yaml, ou yml")

    data = _strip_private_keys(data)

    try:
        cfg = EditorialConfig.model_validate(data)
    except ValidationError as e:
        raise EditorialConfigError(f"Editorial config inválido: {e}") from e

    if str(os.getenv("LOG_LEVEL", "")).strip().upper() == "DEBUG":
        logger.info(f"Editorial config carregado: {p}")

    return cfg


@dataclass(frozen=True, slots=True)
class EditorialConfigLoader:
    default_relpath: str = "configs/editorial.json"
    env_var: str = "EDITORIAL_CONFIG_PATH"

    @property
    def path(self) -> Path:
        raw = str(os.getenv(self.env_var, self.default_relpath)).strip()
        p = Path(raw)
        return p if p.is_absolute() else (Path.cwd() / p).resolve()

    def load(self) -> EditorialConfig:
        return load_editorial_config_from_path(self.path)


def _parse_env_models(raw: str) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    return [p.strip() for p in s.split(",") if p.strip()]


def resolve_model_pool(pool: ModelPool) -> list[str]:
    """Resolve pool de modelos, aplicando override por env.

    Args:
        pool: Pool configurado.

    Returns:
        list[str]: Lista de modelos resolvida.
    """
    if pool.env_override:
        raw = os.getenv(pool.env_override, "")
        models = _parse_env_models(raw)
        if models:
            logger.warning(f"Env override ativo para {pool.env_override}")
            return models
        if str(raw).strip():
            logger.error(f"Env override inválido em {pool.env_override}, a usar config")
    return list(pool.models)


_LOADER = EditorialConfigLoader()
_CACHE: Optional[EditorialConfig] = None


def get_editorial_config(force_reload: bool = False) -> EditorialConfig:
    """Devolve config editorial cacheada.

    Args:
        force_reload: Recarrega do disco.

    Returns:
        EditorialConfig: Config editorial.
    """
    global _CACHE
    if _CACHE is None or force_reload:
        _CACHE = _LOADER.load()
    return _CACHE
