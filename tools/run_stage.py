#!filepath: tools/run_stage.py
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from vozdipovo_app.config import load_app_config
from vozdipovo_app.db.migrate import ensure_schema
from vozdipovo_app.db.sqlite_conn import connect_sqlite
from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.modules.base import StageContext
from vozdipovo_app.modules.judging_stage import JudgingStage
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StageArgs:
    """Parsed arguments.

    Args:
        stage: Stage name.
        limit: Optional limit.
    """

    stage: str
    limit: int


def _sleep(seconds: float) -> None:
    if seconds <= 0:
        return
    time.sleep(seconds)


def _parse_args(argv: list[str]) -> StageArgs:
    stage = str(argv[1] if len(argv) > 1 else "judging").strip() or "judging"
    limit_raw = str(argv[2] if len(argv) > 2 else "0").strip()
    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 0
    return StageArgs(stage=stage, limit=limit)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.stage != "judging":
        raise SystemExit("Este runner só executa judging por agora")

    app_cfg = load_app_config()
    editorial = get_editorial_config()

    db_path = str(app_cfg["paths"]["db"])
    conn = connect_sqlite(db_path)

    try:
        ensure_schema(conn)
        ctx = StageContext(conn=conn, app_cfg=app_cfg, editorial=editorial)

        lim = args.limit or int(editorial.pipeline.judge_limit_per_run)
        throttle = float(editorial.pipeline.throttle_seconds.judge)
        n = JudgingStage(ctx=ctx, limit=lim, throttle_seconds=throttle).run()
        logger.info(f"✅ Julgamento: judged={n}")
        _sleep(throttle)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
