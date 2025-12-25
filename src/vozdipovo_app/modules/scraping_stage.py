#!src/vozdipovo_app/modules/scraping_stage.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Type

from vozdipovo_app.modules.base import Stage, StageContext
from vozdipovo_app.scrapers.base import BaseScraper
from vozdipovo_app.scrapers.bo_scraper import BOScraper
from vozdipovo_app.scrapers.nextjs_scraper import NextJsScraper
from vozdipovo_app.scrapers.rss_scraper import RssScraper
from vozdipovo_app.utils.logger import get_logger
from vozdipovo_app.utils.serialization import load_yaml_dict

logger = get_logger(__name__)

MAX_ATTEMPTS_PER_SITE = 2


def _load_sites(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        logger.error(f"sites.yaml não encontrado, path={path}")
        return []

    res = load_yaml_dict(path)
    if not res.ok:
        logger.error(f"Falha ao ler sites.yaml, path={path}")
        return []

    sites = res.data.get("sites", [])
    if not isinstance(sites, list):
        logger.error(f"sites.yaml inválido, sites não é lista, path={path}")
        return []

    return [s for s in sites if isinstance(s, dict)]


def _sites_path_from_cfg(app_cfg: dict[str, Any]) -> Path:
    p = Path(str(app_cfg.get("paths", {}).get("sites", "configs/sites.yaml")))
    if p.exists():
        return p
    fallback = Path("configs/sites.yaml")
    return fallback


def _scraper_map() -> dict[str, Type[BaseScraper]]:
    return {
        "rss": RssScraper,
        "html": BOScraper,
        "nextjs": NextJsScraper,
    }


@dataclass(frozen=True, slots=True)
class ScrapingStage(Stage):
    """Executa scraping por site seguindo a ordem do sites.yaml, com requeue e retry."""

    ctx: StageContext
    site_filter: Optional[str] = None

    @property
    def normalized_site_filter(self) -> str:
        return str(self.site_filter or "").strip().casefold()

    def _select_sites(self) -> list[dict[str, Any]]:
        cfg = self.ctx.app_cfg if isinstance(self.ctx.app_cfg, dict) else {}
        sites_path = _sites_path_from_cfg(cfg)
        sites = _load_sites(sites_path)
        wanted = self.normalized_site_filter
        if not wanted:
            return sites
        return [
            s for s in sites if str(s.get("name") or "").strip().casefold() == wanted
        ]

    def _run_one(self, site: dict[str, Any]) -> tuple[int, int, int, bool]:
        name = str(site.get("name") or "").strip()
        s_type = str(site.get("type") or "").strip().lower()
        s_cfg = site.get("config") if isinstance(site.get("config"), dict) else {}

        Scraper = _scraper_map().get(s_type)
        if not Scraper:
            logger.warning(f"Tipo de scraper desconhecido, site={name}, type={s_type}")
            return 0, 0, 1, False

        try:
            logger.info(f"Scraper a iniciar, site={name}, type={s_type}")
            stats = Scraper(name, s_cfg, self.ctx.conn).run()
            inserted = int(stats.get("inserted", 0))
            skipped = int(stats.get("skipped", 0))
            errors = int(stats.get("errors", 0))
            ok = errors == 0
            logger.info(
                f"Scraper terminou, site={name}, inserted={inserted}, skipped={skipped}, errors={errors}"
            )
            return inserted, skipped, errors, ok
        except Exception:
            logger.error(f"Scraper falhou com exceção, site={name}", exc_info=True)
            return 0, 0, 1, False

    def run(self) -> int:
        sites = self._select_sites()
        if not sites:
            logger.info("Nenhum site configurado para scraping.")
            return 0

        queue: list[dict[str, Any]] = list(sites)
        inserted_total = 0
        failures: list[dict[str, Any]] = []

        for s in queue:
            inserted, _, _, ok = self._run_one(s)
            inserted_total += inserted
            if not ok:
                failures.append(s)

        if not failures:
            return inserted_total

        logger.warning(f"Requeue ativo, sites_com_falha={len(failures)}, attempts=2")

        retry_failures: list[dict[str, Any]] = []
        for s in failures:
            inserted, _, _, ok = self._run_one(s)
            inserted_total += inserted
            if not ok:
                retry_failures.append(s)

        if retry_failures:
            names = [str(s.get("name") or "").strip() for s in retry_failures]
            logger.error(f"Falhas persistentes após retry, sites={names}")

        return inserted_total


if __name__ == "__main__":
    import sqlite3

    from vozdipovo_app.settings import get_settings

    settings = get_settings()
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        stage = ScrapingStage(
            ctx=StageContext(
                conn=conn, app_cfg=settings.app_cfg, editorial=settings.editorial
            ),
            site_filter=None,
        )
        processed = stage.run()
        conn.commit()
        logger.info(f"done, processed={processed}")
    finally:
        conn.close()
