#!filepath: scripts/run_once.py
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from vozdipovo_app.utils.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

from vozdipovo_app.config import load_app_config
from vozdipovo_app.db.migrate import ensure_schema
from vozdipovo_app.db.sqlite_conn import connect_sqlite
from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.modules.audio_stage import AudioStage
from vozdipovo_app.modules.base import StageContext
from vozdipovo_app.modules.curation_stage import CurationStage
from vozdipovo_app.modules.generation_stage import GenerationStage
from vozdipovo_app.modules.judging_stage import JudgingStage
from vozdipovo_app.modules.publishing_stage import PublishingStage
from vozdipovo_app.modules.revision_stage import RevisionStage
from vozdipovo_app.modules.scraping_stage import ScrapingStage


def _sleep(seconds: float) -> None:
    if seconds <= 0:
        return
    time.sleep(seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        default="full",
        choices=(
            "scraping",
            "judging",
            "generation",
            "revising",
            "publishing",
            "curation",
            "audio",
            "full",
        ),
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    app_cfg = load_app_config()
    editorial = get_editorial_config()

    db_path = str(app_cfg["paths"]["db"])
    conn = connect_sqlite(db_path)

    try:
        ensure_schema(conn)
        ctx = StageContext(conn=conn, app_cfg=app_cfg, editorial=editorial)

        if args.stage in ("scraping", "full"):
            n = ScrapingStage(ctx).run()
            logger.info(f"✅ Scraping: scraped={n}")

        if args.stage in ("judging", "full"):
            lim = args.limit or int(editorial.pipeline.judge_limit_per_run)
            throttle = float(editorial.pipeline.throttle_seconds.judge)
            n = JudgingStage(ctx=ctx, limit=lim, throttle_seconds=throttle).run()
            logger.info(f"✅ Julgamento: judged={n}")
            _sleep(throttle)

        if args.stage in ("generation", "full"):
            lim = args.limit or int(editorial.pipeline.generate_limit_per_run)
            sig = float(editorial.scoring.significance_threshold)
            n = GenerationStage(ctx=ctx, significance_threshold=sig, limit=lim).run()
            logger.info(f"✅ Redação: generated={n}")

        if args.stage in ("revising", "full"):
            lim = args.limit or int(editorial.pipeline.revision_limit_per_run)
            n = RevisionStage(conn=conn, limit=lim).run()
            logger.info(f"✅ Reclassificação: updated={n}")

        if args.stage in ("publishing", "full"):
            lim = args.limit or int(editorial.pipeline.publish_limit_per_run)
            throttle = float(editorial.pipeline.throttle_seconds.wordpress)
            n = PublishingStage(ctx=ctx, limit=lim, throttle_seconds=throttle).run()
            logger.info(f"✅ Publicação: published={n}")
            _sleep(throttle)

        if args.stage in ("curation", "full"):
            hp = editorial.homepage
            n = CurationStage(
                ctx=ctx,
                hours=int(hp.time_window_hours),
                breaking_threshold=float(hp.breaking.editorial_threshold),
                breaking_limit=int(hp.breaking.limit),
                breaking_category_id=int(hp.breaking.category_id),
                featured_threshold=float(hp.featured.editorial_threshold),
                featured_limit=int(hp.featured.limit),
                featured_category_id=int(hp.featured.category_id),
            ).run()
            logger.info(f"✅ Curadoria: highlights={n}")

        if args.stage in ("audio", "full"):
            a = editorial.audio
            highlight_types = set(a.highlights or ["BREAKING", "FEATURED"])
            n = AudioStage(
                ctx=ctx,
                enabled=bool(a.enabled),
                only_for_highlights=bool(a.only_for_highlights),
                highlight_types=highlight_types,
                output_subdir=str(a.output_subdir or "audio"),
                limit=50,
            ).run()
            logger.info(f"✅ Áudio: generated={n}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
