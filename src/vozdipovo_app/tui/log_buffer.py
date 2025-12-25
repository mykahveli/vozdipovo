#!filepath: src/vozdipovo_app/tui/log_buffer.py
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Iterable, Tuple


@dataclass(slots=True, frozen=True)
class LogLine:
    """A single log line for display."""

    ts_utc: datetime
    text: str


class LogBuffer:
    """Thread safe buffer for log lines."""

    def __init__(self, *, max_lines: int) -> None:
        self._max_lines = int(max_lines)
        self._lock = threading.Lock()
        self._lines: Deque[LogLine] = deque(maxlen=self._max_lines)

    @property
    def max_lines(self) -> int:
        return self._max_lines

    def append(self, text: str) -> None:
        now = datetime.now(tz=timezone.utc)
        line = LogLine(ts_utc=now, text=text)
        with self._lock:
            self._lines.append(line)

    def snapshot(self) -> Tuple[LogLine, ...]:
        with self._lock:
            return tuple(self._lines)

    def as_text(self) -> str:
        items = self.snapshot()
        return "\n".join([l.text for l in items])

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()

    def extend(self, texts: Iterable[str]) -> None:
        for t in texts:
            self.append(t)
