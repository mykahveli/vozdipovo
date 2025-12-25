#!scripts/reset_db.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vozdipovo_app.db.reset import reset_database_file
from vozdipovo_app.settings import get_settings
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        logger.error("Recusado, falta yes")
        return 2

    settings = get_settings()
    res = reset_database_file(settings.db_path)
    if not res.ok:
        return 2

    logger.info(f"DB recriada, path={res.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
