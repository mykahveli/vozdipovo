#!src/vozdipovo_app/tools/pipeline_doctor.py
from __future__ import annotations

import argparse
import importlib
import inspect
import logging
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from vozdipovo_app.db.migrate import ensure_schema, recreate_schema
from vozdipovo_app.settings import get_settings
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DoctorArgs:
    stage: str
    site: Optional[str]
    recreate_db: bool
    yes: bool
    http_debug: bool
    limit: Optional[int]
    throttle_seconds: Optional[float]
    significance_threshold: Optional[float]


def _detect_import_origin() -> str:
    import vozdipovo_app as pkg

    p = Path(str(getattr(pkg, "__file__", "") or "")).resolve()
    return str(p)


def _add_project_src_to_sys_path() -> None:
    here = Path(__file__).resolve()
    root = here.parent.parent.parent.parent
    src = root / "src"
    if src.exists():
        s = str(src)
        if s not in sys.path:
            sys.path.insert(0, s)


def _parse_args(argv: Optional[list[str]] = None) -> DoctorArgs:
    parser = argparse.ArgumentParser(prog="pipeline_doctor")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--site", default=None)
    parser.add_argument("--recreate-db", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--http-debug", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--throttle-seconds", type=float, default=None)
    parser.add_argument("--significance-threshold", type=float, default=None)
    ns = parser.parse_args(argv)
    return DoctorArgs(
        stage=str(ns.stage).strip(),
        site=ns.site,
        recreate_db=bool(ns.recreate_db),
        yes=bool(ns.yes),
        http_debug=bool(ns.http_debug),
        limit=ns.limit,
        throttle_seconds=ns.throttle_seconds,
        significance_threshold=ns.significance_threshold,
    )


def _normalize_stage_name(stage: str) -> str:
    s = str(stage or "").strip().casefold()
    aliases: dict[str, str] = {
        "scraping": "scraping",
        "scrape": "scraping",
        "judging": "judging",
        "judge": "judging",
        "julgamento": "judging",
        "judging_stage": "judging",
        "generation": "generation",
        "generate": "generation",
        "geracao": "generation",
        "geração": "generation",
        "revisao": "revision",
        "revisão": "revision",
        "revision": "revision",
        "revising": "revision",
        "publishing": "publishing",
        "publish": "publishing",
        "publicacao": "publishing",
        "publicação": "publishing",
        "curadoria": "curation",
        "curation": "curation",
        "curating": "curation",
        "audio": "audio",
        "áudio": "audio",
    }
    return aliases.get(s, s)


def _lazy_stage_factory(stage: str) -> Callable[[], Any]:
    m = _normalize_stage_name(stage)
    mapping = {
        "scraping": "vozdipovo_app.modules.scraping_stage.ScrapingStage",
        "judging": "vozdipovo_app.modules.judging_stage.JudgingStage",
        "generation": "vozdipovo_app.modules.generation_stage.GenerationStage",
        "revision": "vozdipovo_app.modules.revision_stage.RevisionStage",
        "publishing": "vozdipovo_app.modules.publishing_stage.PublishingStage",
        "curation": "vozdipovo_app.modules.curation_stage.CurationStage",
        "audio": "vozdipovo_app.modules.audio_stage.AudioStage",
    }
    dotted = mapping.get(m)
    if not dotted:
        raise ValueError(f"Stage inválido: {stage}")
    mod_name, attr = dotted.rsplit(".", 1)

    def _factory() -> Any:
        mod = importlib.import_module(mod_name)
        return getattr(mod, attr)

    return _factory


def _enable_http_debug() -> None:
    for n in ("urllib3", "requests", "httpcore", "httpx"):
        logging.getLogger(n).setLevel(logging.DEBUG)
    logger.warning("HTTP debug ativo")


def _cfg_default(settings: Any, key: str, fallback: Any) -> Any:
    pipeline = (
        settings.app_cfg.get("pipeline", {})
        if isinstance(settings.app_cfg, dict)
        else {}
    )
    if not isinstance(pipeline, dict):
        return fallback
    return pipeline.get(key, fallback)


def _instantiate_stage(
    stage_cls: Any, ctx: Any, args: DoctorArgs, settings: Any
) -> Any:
    sig = inspect.signature(stage_cls.__init__)
    params = {p.name for p in sig.parameters.values() if p.name != "self"}
    kwargs: dict[str, Any] = {}

    if "site_filter" in params and _normalize_stage_name(args.stage) == "scraping":
        kwargs["site_filter"] = args.site

    if "limit" in params:
        default_limit_key = f"{_normalize_stage_name(args.stage)}_limit"
        kwargs["limit"] = int(
            args.limit
            if args.limit is not None
            else int(_cfg_default(settings, default_limit_key, 50))
        )

    if "throttle_seconds" in params:
        kwargs["throttle_seconds"] = float(
            args.throttle_seconds
            if args.throttle_seconds is not None
            else float(_cfg_default(settings, "judging_throttle_seconds", 0.0))
        )

    if "significance_threshold" in params:
        kwargs["significance_threshold"] = float(
            args.significance_threshold
            if args.significance_threshold is not None
            else float(_cfg_default(settings, "significance_threshold", 0.0))
        )

    if "ctx" in params:
        return stage_cls(ctx=ctx, **kwargs)

    return stage_cls(ctx, **kwargs)


def main(argv: Optional[list[str]] = None) -> int:
    _add_project_src_to_sys_path()
    args = _parse_args(argv)

    logger.info(f"Python={platform.python_version()}, exe={sys.executable}")
    logger.info(f"Import origin vozdipovo_app={_detect_import_origin()}")

    if args.http_debug:
        _enable_http_debug()

    settings = get_settings()
    db_path = settings.db_path
    logger.info(f"DB path={db_path}")

    conn = None
    try:
        if args.recreate_db:
            if not args.yes:
                raise SystemExit("Recreate db pedido sem yes")
            conn = recreate_schema(db_path)
        else:
            conn = ensure_schema(db_path)

        base_mod = __import__("vozdipovo_app.modules.base", fromlist=["StageContext"])
        ctx = base_mod.StageContext(
            conn=conn,
            app_cfg=settings.app_cfg,
            editorial=settings.editorial,
        )

        stage_cls = _lazy_stage_factory(args.stage)()
        stage_obj = _instantiate_stage(stage_cls, ctx, args, settings)

        processed = int(stage_obj.run())

        try:
            conn.commit()
            logger.info("DB commit ok")
        except Exception:
            logger.error("DB commit falhou", exc_info=True)
            raise

        logger.info(f"Stage concluído, stage={args.stage}, processed={processed}")
        return 0
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
