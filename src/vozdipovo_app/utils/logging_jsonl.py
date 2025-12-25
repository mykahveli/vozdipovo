#!filepath: src/vozdipovo_app/utils/logging_jsonl.py
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class JsonlFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in {"msg", "args", "exc_info", "exc_text", "stack_info"}
            and not k.startswith("_")
        }
        payload["extra"] = extras
        return json.dumps(payload, ensure_ascii=False)
