#!scripts/pipeline_trace.py
from __future__ import annotations

import importlib
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from vozdipovo_app.settings import get_settings
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__, level="DEBUG")


@dataclass(frozen=True, slots=True)
class TraceArgs:
    stage: str


def _parse(argv: Optional[list[str]] = None) -> TraceArgs:
    a = list(argv or sys.argv[1:])
    stage = "scraping"
    if a:
        stage = str(a[0]).strip()
    return TraceArgs(stage=stage)


def _origin(name: str) -> str:
    mod = importlib.import_module(name)
    p = Path(str(getattr(mod, "__file__", "") or "")).resolve()
    return str(p)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse(argv)

    logger.info(f"Python={platform.python_version()}, exe={sys.executable}")
    logger.info(f"sys.path[0]={sys.path[0] if sys.path else ''}")
    logger.info(f"vozdipovo_app origin={_origin('vozdipovo_app')}")
    logger.info(f"pydantic origin={_origin('pydantic')}")
    logger.info(f"pydantic_settings origin={_origin('pydantic_settings')}")

    settings = get_settings()
    logger.info(f"db_path={settings.db_path}")
    logger.info(f"configs_dir={settings.paths.configs_dir}")
    logger.info(f"sites_yaml={settings.app_cfg.get('paths', {}).get('sites')}")

    stage_map = {
        "scraping": "vozdipovo_app.modules.scraping_stage.ScrapingStage",
        "judging": "vozdipovo_app.modules.judging_stage.JudgingStage",
        "generation": "vozdipovo_app.modules.generation_stage.GenerationStage",
        "revision": "vozdipovo_app.modules.revision_stage.RevisionStage",
        "publishing": "vozdipovo_app.modules.publishing_stage.PublishingStage",
        "curation": "vozdipovo_app.modules.curation_stage.CurationStage",
        "audio": "vozdipovo_app.modules.audio_stage.AudioStage",
    }

    dotted = stage_map.get(str(args.stage).lower())
    if not dotted:
        raise SystemExit(f"Stage inválido: {args.stage}")

    mod_name, attr = dotted.rsplit(".", 1)
    logger.info(f"Import stage module={mod_name}, attr={attr}")
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, attr)
    logger.info(f"Stage class={cls}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
