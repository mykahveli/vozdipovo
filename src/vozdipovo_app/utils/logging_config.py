#!filepath: src/vozdipovo_app/utils/logging_config.py
from __future__ import annotations

import atexit
import logging
import queue
from dataclasses import dataclass
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, Field
from rich.logging import RichHandler

from vozdipovo_app.utils.logging_jsonl import JsonlFormatter


class LoggingSettings(BaseSettings):
    log_dir: Path = Field(default=Path("data/logs"), env="VOZDIPO_LOG_DIR")
    level: str = Field(default="INFO", env="VOZDIPO_LOG_LEVEL")
    file_name: str = Field(default="app.log", env="VOZDIPO_LOG_FILE")
    jsonl_name: str = Field(default="app.jsonl", env="VOZDIPO_LOG_JSONL")
    max_bytes: int = Field(default=10_000_000, env="VOZDIPO_LOG_MAX_BYTES")
    backup_count: int = Field(default=5, env="VOZDIPO_LOG_BACKUP_COUNT")
    rich_tracebacks: bool = Field(default=True, env="VOZDIPO_RICH_TRACEBACKS")

    class Config:
        env_file = ".env"
        case_sensitive = False


@dataclass(slots=True)
class _Runtime:
    settings: LoggingSettings
    q: queue.Queue[logging.LogRecord]
    listener: QueueListener


_runtime: Optional[_Runtime] = None


def configure_logging(
    *, settings: Optional[LoggingSettings] = None, enable_console: bool = True
) -> None:
    global _runtime
    if _runtime is not None:
        return

    s = settings or LoggingSettings()
    s.log_dir.mkdir(parents=True, exist_ok=True)

    q: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=10000)

    file_handler = RotatingFileHandler(
        filename=str(s.log_dir / s.file_name),
        maxBytes=int(s.max_bytes),
        backupCount=int(s.backup_count),
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )

    jsonl_handler = RotatingFileHandler(
        filename=str(s.log_dir / s.jsonl_name),
        maxBytes=int(s.max_bytes),
        backupCount=int(s.backup_count),
        encoding="utf-8",
    )
    jsonl_handler.setLevel(logging.DEBUG)
    jsonl_handler.setFormatter(JsonlFormatter())

    handlers = [file_handler, jsonl_handler]
    if enable_console:
        console = RichHandler(rich_tracebacks=bool(s.rich_tracebacks), show_path=False)
        console.setLevel(getattr(logging, s.level.upper(), logging.INFO))
        console.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(console)

    listener = QueueListener(q, *handlers, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    root.addHandler(QueueHandler(q))

    _runtime = _Runtime(settings=s, q=q, listener=listener)
