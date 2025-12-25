#!scripts/pipeline_doctor.py
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
if SRC.exists():
    s = str(SRC)
    if s not in sys.path:
        sys.path.insert(0, s)

from vozdipovo_app.tools.pipeline_doctor import main

if __name__ == "__main__":
    raise SystemExit(main())
