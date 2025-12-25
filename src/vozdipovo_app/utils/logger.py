#!src/vozdipovo_app/utils/logger.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.logging import RichHandler


class LoggingSettings(BaseSettings):
    """Configuração de logging isolada do resto do ambiente.

    Carrega variáveis a partir de .env e do ambiente, mas não falha com chaves
    não relacionadas com logging.

    Attributes:
        log_dir: Diretório de logs.
        console_level: Nível do handler de consola.
        file_level: Nível do handler de ficheiro.
        file_name: Nome do ficheiro de log.
        max_bytes: Tamanho máximo do ficheiro antes de rodar.
        backup_count: Quantos backups manter.
        rich_tracebacks: Se ativa tracebacks ricos na consola.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        env_prefix="VOZDIPO_",
    )

    log_dir: Path = Field(default=Path("data/logs"), validation_alias="VOZDIPO_LOG_DIR")
    console_level: str = Field(default="INFO", validation_alias="VOZDIPO_CONSOLE_LEVEL")
    file_level: str = Field(default="DEBUG", validation_alias="VOZDIPO_FILE_LEVEL")
    file_name: str = Field(default="app.log", validation_alias="VOZDIPO_LOG_FILE")
    max_bytes: int = Field(default=5_000_000, validation_alias="VOZDIPO_LOG_MAX_BYTES")
    backup_count: int = Field(default=5, validation_alias="VOZDIPO_LOG_BACKUP_COUNT")
    rich_tracebacks: bool = Field(
        default=True, validation_alias="VOZDIPO_RICH_TRACEBACKS"
    )


@dataclass(slots=True)
class _Runtime:
    configured: bool = False


_runtime: _Runtime = _Runtime()


def configure_logging(*, settings: Optional[LoggingSettings] = None) -> None:
    """Configura logging global uma vez, com consola Rich e ficheiro rotativo.

    Args:
        settings: Override opcional para testes.
    """
    if _runtime.configured:
        return

    s = settings or LoggingSettings()
    s.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console_level = getattr(logging, s.console_level.upper(), logging.INFO)
    file_level = getattr(logging, s.file_level.upper(), logging.DEBUG)

    console_handler = RichHandler(
        rich_tracebacks=bool(s.rich_tracebacks),
        markup=True,
        show_path=False,
        show_level=True,
        log_time_format="[%X]",
    )
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    file_handler = RotatingFileHandler(
        filename=str(s.log_dir / s.file_name),
        maxBytes=int(s.max_bytes),
        backupCount=int(s.backup_count),
        encoding="utf_8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )

    root.addHandler(console_handler)
    root.addHandler(file_handler)

    for noisy in ("urllib3", "httpcore", "httpx", "readability", "bs4"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.captureWarnings(True)
    _runtime.configured = True


def get_logger(name: str = "vozdipovo_app", level: str | None = None) -> logging.Logger:
    """Devolve um logger já com logging global configurado.

    Args:
        name: Nome do logger.
        level: Override opcional do nível.

    Returns:
        Logger configurado.
    """
    configure_logging()
    logger = logging.getLogger(name)
    if level:
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger
