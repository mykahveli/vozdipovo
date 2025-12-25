#!src/vozdipovo_app/tui/settings.py
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TuiSettings(BaseSettings):
    """Settings para a UI de terminal.

    Attributes:
        repo_root: Raiz do repositório.
        run_script: Script que corre uma iteração da pipeline.
        refresh_ms: Intervalo de refresh.
        max_log_lines: Máximo de linhas de log na UI.
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    repo_root: Path = Field(default=Path("."), validation_alias="VOZDIPO_REPO_ROOT")
    run_script: Path = Field(
        default=Path("scripts/run_once.py"), validation_alias="VOZDIPO_RUN_SCRIPT"
    )
    refresh_ms: int = Field(default=150, validation_alias="VOZDIPO_TUI_REFRESH_MS")
    max_log_lines: int = Field(
        default=2500, validation_alias="VOZDIPO_TUI_MAX_LOG_LINES"
    )
