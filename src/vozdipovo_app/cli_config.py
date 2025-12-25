#!filepath: src/vozdipovo_app/cli_config.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from vozdipovo_app.editorial.config import (
    EditorialConfigError,
    load_editorial_config_from_path,
)
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vozdipovo_config")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate_config")
    validate.add_argument("path", nargs="?", default="configs/editorial.json")

    dump = sub.add_parser("dump_config")
    dump.add_argument("path", nargs="?", default="configs/editorial.json")

    return parser


def _validate(path: Path) -> int:
    try:
        cfg = load_editorial_config_from_path(path)
    except EditorialConfigError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"Erro inesperado ao validar config: {e}")
        return 2

    logger.info(f"Config ok, version={cfg.version}, path={path.expanduser().resolve()}")
    return 0


def _dump(path: Path) -> int:
    try:
        cfg = load_editorial_config_from_path(path)
    except EditorialConfigError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"Erro inesperado ao carregar config: {e}")
        return 2

    payload: dict[str, Any] = cfg.dict(by_alias=True)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    path = Path(str(args.path))

    if args.cmd == "validate_config":
        return _validate(path)

    if args.cmd == "dump_config":
        return _dump(path)

    logger.error(f"Comando desconhecido: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
