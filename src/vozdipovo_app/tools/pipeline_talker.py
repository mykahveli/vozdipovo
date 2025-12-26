#!src/vozdipovo_app/tools/pipeline_talker.py
from __future__ import annotations

import argparse
import importlib
import inspect
import logging
import platform
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from vozdipovo_app.db.migrate import ensure_schema
from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.settings import get_settings
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


_PIPELINE_ORDER = [
    "scraping",
    "judging",
    "generation",
    "revision",
    "publishing",
    "curation",
    "audio",
]


@dataclass(frozen=True, slots=True)
class TalkerArgs:
    from_stage: str
    to_stage: str
    limit: int
    site: Optional[str]
    http_debug: bool


def _add_project_src_to_sys_path() -> None:
    here = Path(__file__).resolve()
    root = here.parent.parent.parent.parent
    src = root / "src"
    if src.exists():
        s = str(src)
        if s not in sys.path:
            sys.path.insert(0, s)


def _normalize(stage: str) -> str:
    s = str(stage or "").strip().casefold()
    aliases = {
        "scrape": "scraping",
        "scraping": "scraping",
        "judge": "judging",
        "judging": "judging",
        "generation": "generation",
        "generate": "generation",
        "revision": "revision",
        "revisao": "revision",
        "revisão": "revision",
        "publishing": "publishing",
        "publish": "publishing",
        "curation": "curation",
        "curadoria": "curation",
        "audio": "audio",
        "áudio": "audio",
    }
    return aliases.get(s, s)


def _parse_args(argv: Optional[list[str]] = None) -> TalkerArgs:
    p = argparse.ArgumentParser(prog="pipeline_talker")
    p.add_argument("--from-stage", default="scraping")
    p.add_argument("--to-stage", default="audio")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--site", default=None)
    p.add_argument("--http-debug", action="store_true")
    ns = p.parse_args(argv)
    return TalkerArgs(
        from_stage=_normalize(ns.from_stage),
        to_stage=_normalize(ns.to_stage),
        limit=int(ns.limit),
        site=ns.site,
        http_debug=bool(ns.http_debug),
    )


def _enable_http_debug() -> None:
    for n in ("urllib3", "requests", "httpcore", "httpx"):
        logging.getLogger(n).setLevel(logging.DEBUG)
    logger.warning("HTTP debug ativo")


def _lazy_stage_factory(stage: str) -> Callable[[], Any]:
    mapping = {
        "scraping": "vozdipovo_app.modules.scraping_stage.ScrapingStage",
        "judging": "vozdipovo_app.modules.judging_stage.JudgingStage",
        "generation": "vozdipovo_app.modules.generation_stage.GenerationStage",
        "revision": "vozdipovo_app.modules.revision_stage.RevisionStage",
        "publishing": "vozdipovo_app.modules.publishing_stage.PublishingStage",
        "curation": "vozdipovo_app.modules.curation_stage.CurationStage",
        "audio": "vozdipovo_app.modules.audio_stage.AudioStage",
    }
    dotted = mapping.get(stage)
    if not dotted:
        raise ValueError(f"Stage inválido: {stage}")
    mod_name, attr = dotted.rsplit(".", 1)

    def _factory() -> Any:
        mod = importlib.import_module(mod_name)
        return getattr(mod, attr)

    return _factory


def _instantiate_stage(
    stage_cls: Any, ctx: Any, *, stage: str, args: TalkerArgs
) -> Any:
    sig = inspect.signature(stage_cls.__init__)
    params = {p.name for p in sig.parameters.values() if p.name != "self"}
    kwargs: dict[str, Any] = {}

    if "site_filter" in params and stage == "scraping":
        kwargs["site_filter"] = args.site

    if "limit" in params:
        kwargs["limit"] = int(args.limit)

    if "significance_threshold" in params:
        kwargs["significance_threshold"] = float(
            get_editorial_config().significance_threshold
        )

    if "ctx" in params:
        return stage_cls(ctx=ctx, **kwargs)
    return stage_cls(ctx, **kwargs)


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    try:
        row = conn.execute(sql, params).fetchone()
        if not row:
            return 0
        return int(row[0] or 0)
    except Exception:
        return 0


def _snapshot(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "legal_docs": _count(conn, "SELECT COUNT(1) FROM legal_docs"),
        "news_articles": _count(conn, "SELECT COUNT(1) FROM news_articles"),
        "judged": _count(
            conn, "SELECT COUNT(1) FROM news_articles WHERE review_status='JUDGED'"
        ),
        "generated": _count(
            conn, "SELECT COUNT(1) FROM news_articles WHERE review_status='GENERATED'"
        ),
        "reviewed": _count(
            conn, "SELECT COUNT(1) FROM news_articles WHERE review_status='REVIEWED'"
        ),
        "failed": _count(
            conn,
            "SELECT COUNT(1) FROM news_articles WHERE review_status IN ('FAILED','ERROR')",
        ),
        "retry": _count(
            conn, "SELECT COUNT(1) FROM news_articles WHERE review_status='RETRY'"
        ),
    }


def _stage_range(from_stage: str, to_stage: str) -> list[str]:
    if from_stage not in _PIPELINE_ORDER:
        raise ValueError(f"from_stage inválido: {from_stage}")
    if to_stage not in _PIPELINE_ORDER:
        raise ValueError(f"to_stage inválido: {to_stage}")
    a = _PIPELINE_ORDER.index(from_stage)
    b = _PIPELINE_ORDER.index(to_stage)
    if a > b:
        a, b = b, a
    return _PIPELINE_ORDER[a : b + 1]


def main(argv: Optional[list[str]] = None) -> int:
    _add_project_src_to_sys_path()
    args = _parse_args(argv)

    logger.info(f"Python={platform.python_version()}, exe={sys.executable}")
    if args.http_debug:
        _enable_http_debug()

    settings = get_settings()
    logger.info(f"DB path={settings.db_path}")

    conn = ensure_schema(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        cfg = get_editorial_config()
        logger.info(
            f"Editorial config ok, significance_threshold={cfg.significance_threshold}, quality={cfg.quality.model_dump() if hasattr(cfg.quality, 'model_dump') else cfg.quality.dict()}"
        )

        base_mod = __import__("vozdipovo_app.modules.base", fromlist=["StageContext"])
        ctx = base_mod.StageContext(
            conn=conn, app_cfg=settings.app_cfg, editorial=settings.editorial
        )

        for stage_name in _stage_range(args.from_stage, args.to_stage):
            before = _snapshot(conn)
            logger.info(f"▶️ Stage={stage_name} (antes={before})")

            stage_cls = _lazy_stage_factory(stage_name)()
            stage_obj = _instantiate_stage(stage_cls, ctx, stage=stage_name, args=args)

            processed = int(stage_obj.run())
            conn.commit()

            after = _snapshot(conn)
            logger.info(f"✅ Stage={stage_name} processed={processed} (depois={after})")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
