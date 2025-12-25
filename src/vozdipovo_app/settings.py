#!src/vozdipovo_app/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, ValidationError

from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.editorial.models import EditorialConfig
from vozdipovo_app.utils.logger import get_logger
from vozdipovo_app.utils.project_paths import ProjectPaths

logger = get_logger(__name__)

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    import yaml
except Exception:
    yaml = None


class SettingsError(RuntimeError):
    """Erro ao carregar ou validar settings."""


class RagConfig(BaseModel):
    """Config para RAG."""

    embed_model: str = ""
    chunk_size: int = 1200
    chunk_overlap: int = 200
    top_k: int = 24

    model_config = {"extra": "allow"}


class PathsConfig(BaseModel):
    """Paths do sistema."""

    db: str = "configs/vozdipovo.db"
    textos: str = "data/textos"
    prompt: str = "configs/prompts/reporter.md"
    prompt_revisao: str = "configs/prompts/editor.md"
    out_markdown: str = "data/out_markdown"
    data_root: str = "data"
    sites: str = "configs/sites.yaml"

    model_config = {"extra": "allow"}


class ApiConfig(BaseModel):
    """Config de API."""

    base_url: str = ""
    api_version: str = "v1"
    version: str = "v1"
    model: str = ""
    temperature: float = 0.25
    top_p: float = 0.85
    max_tokens: int = 1536
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    user_agent: str = ""

    model_config = {"extra": "allow"}


class WordPressConfig(BaseModel):
    """Config WordPress."""

    base_url: str = ""
    username: str = ""
    app_password: str = ""
    default_status: str = "publish"
    timeout: int = 30
    rate_sleep: float = 1.0

    model_config = {"extra": "allow"}


class AppConfig(BaseModel):
    """Config principal."""

    rag: RagConfig = RagConfig()
    paths: PathsConfig = PathsConfig()
    api: ApiConfig = ApiConfig()
    wordpress: WordPressConfig = WordPressConfig()
    structured_json: bool = True
    api_key: str = ""
    app_env: str = "production"

    model_config = {"extra": "allow"}

    def to_runtime_dict(self, paths: ProjectPaths) -> Dict[str, Any]:
        """Converte config para dict runtime.

        Args:
            paths: Paths resolvidos do projeto.

        Returns:
            Dict[str, Any]: Payload runtime.
        """
        payload: Dict[str, Any] = self.model_dump()
        payload["paths"] = _normalize_path_map(
            payload.get("paths", {}), root=paths.root
        )
        return payload


@dataclass(frozen=True, slots=True)
class Settings:
    """Settings unificados.

    Attributes:
        app_cfg: Config da app em dict.
        editorial: Config editorial validado.
        paths: Paths do projeto.
    """

    app_cfg: Dict[str, Any]
    editorial: EditorialConfig
    paths: ProjectPaths

    @property
    def config_dir(self) -> Path:
        """Diretório de configs."""
        return self.paths.configs_dir

    @property
    def db_path(self) -> Path:
        """Path da base de dados."""
        raw = str(self.app_cfg.get("paths", {}).get("db", ""))
        return Path(raw).expanduser().resolve()


def load_app_config(paths: Optional[ProjectPaths] = None) -> Dict[str, Any]:
    """Carrega, faz merge e valida config da app.

    Args:
        paths: Paths resolvidos.

    Returns:
        Dict[str, Any]: Config runtime.

    Raises:
        SettingsError: Em caso de falha.
    """
    if load_dotenv is not None:
        load_dotenv(override=False)

    resolved_paths = paths or ProjectPaths.discover()
    env_name = str(os.getenv("APP_ENV", "production") or "production").strip()

    default_path = (resolved_paths.configs_dir / "default.yaml").resolve()
    profile_path = (resolved_paths.configs_dir / f"config.{env_name}.yaml").resolve()

    base = _read_yaml_mapping(default_path, required=True)
    overlay = _read_yaml_mapping(profile_path, required=False)

    merged = _deep_merge(base, overlay)

    api_key = str(os.getenv("PUBLICAI_API_KEY", "") or "").strip()
    if api_key:
        merged["api_key"] = api_key

    merged["app_env"] = env_name

    _override_wordpress_from_env(merged)

    try:
        model = AppConfig.model_validate(merged)
    except ValidationError as e:
        raise SettingsError(f"Config validation failed: {e}") from e

    logger.info(
        f"Loaded app config, env={env_name}, default={default_path}, profile_exists={profile_path.exists()}"
    )
    return model.to_runtime_dict(resolved_paths)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devolve settings cacheados.

    Returns:
        Settings: Settings carregados.
    """
    paths = ProjectPaths.discover()
    app_cfg = load_app_config(paths)
    editorial = get_editorial_config()
    return Settings(app_cfg=app_cfg, editorial=editorial, paths=paths)


def reload_settings() -> Settings:
    """Recarrega settings.

    Returns:
        Settings: Settings recarregados.
    """
    get_settings.cache_clear()
    return get_settings()


def _read_yaml_mapping(path: Path, required: bool) -> Dict[str, Any]:
    if not path.exists():
        if required:
            raise SettingsError(f"Missing config file: {path}")
        return {}

    if yaml is None:
        raise SettingsError("YAML support missing, install PyYAML")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf8"))
    except Exception as e:
        raise SettingsError(f"Invalid YAML at {path}: {e}") from e

    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise SettingsError(f"Top level YAML must be a mapping at {path}")

    return raw


def _deep_merge(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: v for k, v in a.items()}
    for k, v in b.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _normalize_path_map(raw: object, root: Path) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        key = str(k)
        val = str(v)
        p = Path(val).expanduser()
        if not p.is_absolute():
            p = (root / p).resolve()
        out[key] = str(p)
    return out


def _override_wordpress_from_env(merged: Dict[str, Any]) -> None:
    wp = merged.get("wordpress") if isinstance(merged.get("wordpress"), dict) else {}
    base_url = str(os.getenv("WP_BASE_URL", "") or "").strip()
    username = str(os.getenv("WP_USERNAME", "") or "").strip()
    app_password = str(os.getenv("WP_APP_PASSWORD", "") or "").strip()

    if base_url:
        wp["base_url"] = base_url
    if username:
        wp["username"] = username
    if app_password:
        wp["app_password"] = app_password

    merged["wordpress"] = wp
