#!filepath: src/vozdipovo_app/modules/base.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol

from vozdipovo_app.editorial.models import EditorialConfig


class Stage(Protocol):
    """A pipeline stage."""

    def run(self) -> int:
        """Run stage.

        Returns:
            int: Count of processed items.
        """


@dataclass(frozen=True, slots=True)
class StageContext:
    """Shared context passed to stages."""

    conn: sqlite3.Connection
    app_cfg: dict
    editorial: EditorialConfig
