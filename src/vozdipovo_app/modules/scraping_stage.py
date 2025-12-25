#!src/vozdipovo_app/modules/scraping_stage.py
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from vozdipovo_app.modules.base import Stage, StageContext
from vozdipovo_app.scrapers.base import BaseScraper
from vozdipovo_app.utils.logger import get_logger
from vozdipovo_app.utils.serialization import load_yaml_dict

logger = get_logger(__name__)


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


def _load_scraper_class(dotted: str) -> type[BaseScraper]:
    mod_name, attr = str(dotted).rsplit(".", 1)
    mod = importlib.import_module(mod_name)
    Scraper = getattr(mod, attr)
    if not isinstance(Scraper, type):
        raise TypeError(f"Scraper inválido, dotted={dotted}")
    return Scraper


@dataclass(frozen=True, slots=True)
class SiteRunResult:
    """Resultado de uma tentativa de scraping por site."""

    site_name: str
    site_type: str
    attempt: int
    inserted: int
    skipped: int
    errors: int
    ok: bool
    error_message: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ScrapingStage(Stage):
    """Executa scraping seguindo a ordem em sites.yaml, com retry por falha."""

    ctx: StageContext
    site_filter: Optional[str] = None

    @property
    def normalized_site_filter(self) -> str:
        return str(self.site_filter or "").strip().casefold()

    def run(self) -> int:
        cfg = self.ctx.app_cfg
        sites_path = Path(str(cfg.get("paths", {}).get("sites", "configs/sites.yaml")))
        if not sites_path.exists():
            sites_path = Path("configs/sites.yaml")

        sites = _load_sites(sites_path)
        if not sites:
            return 0

        scraper_dotted = {
            "rss": "vozdipovo_app.scrapers.rss_scraper.RssScraper",
            "html": "vozdipovo_app.scrapers.bo_scraper.BOScraper",
            "nextjs": "vozdipovo_app.scrapers.nextjs_scraper.NextJsScraper",
        }

        wanted = self.normalized_site_filter
        ordered = self._select_sites_in_order(sites, wanted)
        if wanted and not ordered:
            logger.error(
                f"Filtro de site não correspondeu a nenhum site, site_filter={self.site_filter}"
            )
            return 0

        results: list[SiteRunResult] = []
        retry_queue: list[dict[str, Any]] = []

        inserted_total = 0

        for site in ordered:
            r = self._run_one(site, attempt=1, scraper_dotted=scraper_dotted)
            results.append(r)
            inserted_total += int(r.inserted)
            if not r.ok:
                retry_queue.append(site)

        if retry_queue:
            for site in retry_queue:
                r = self._run_one(site, attempt=2, scraper_dotted=scraper_dotted)
                results.append(r)
                inserted_total += int(r.inserted)

        self._log_summary(results)
        return inserted_total

    def _select_sites_in_order(
        self, sites: list[dict[str, Any]], wanted: str
    ) -> list[dict[str, Any]]:
        if not wanted:
            return [s for s in sites if self._site_has_name(s)]
        out: list[dict[str, Any]] = []
        for s in sites:
            name = str(s.get("name") or "").strip()
            if name.casefold() == wanted:
                out.append(s)
        return out

    def _site_has_name(self, site: dict[str, Any]) -> bool:
        return bool(str(site.get("name") or "").strip())

    def _run_one(
        self,
        site: dict[str, Any],
        *,
        attempt: int,
        scraper_dotted: dict[str, str],
    ) -> SiteRunResult:
        name = str(site.get("name") or "").strip()
        s_type = str(site.get("type") or "").strip().lower()
        s_cfg = site.get("config") if isinstance(site.get("config"), dict) else {}

        dotted = scraper_dotted.get(s_type)
        if not dotted:
            msg = f"Tipo de scraper desconhecido, site={name}, type={s_type}"
            logger.warning(msg)
            return SiteRunResult(
                site_name=name,
                site_type=s_type,
                attempt=int(attempt),
                inserted=0,
                skipped=0,
                errors=1,
                ok=False,
                error_message=msg,
            )

        logger.info(f"Scraper a iniciar, site={name}, type={s_type}, attempt={attempt}")

        try:
            Scraper = _load_scraper_class(dotted)
        except Exception as e:
            msg = f"Falha no import do scraper, site={name}, type={s_type}, err={e}"
            logger.error(msg, exc_info=True)
            return SiteRunResult(
                site_name=name,
                site_type=s_type,
                attempt=int(attempt),
                inserted=0,
                skipped=0,
                errors=1,
                ok=False,
                error_message=msg,
            )

        try:
            scraper = Scraper(name, dict(s_cfg or {}), self.ctx.conn)
            stats = scraper.run()
            inserted = int(stats.get("inserted", 0))
            skipped = int(stats.get("skipped", 0))
            errors = int(stats.get("errors", 0))
            ok = errors == 0
            logger.info(
                f"Scraper terminou, site={name}, inserted={inserted}, skipped={skipped}, errors={errors}"
            )
            return SiteRunResult(
                site_name=name,
                site_type=s_type,
                attempt=int(attempt),
                inserted=inserted,
                skipped=skipped,
                errors=errors,
                ok=ok,
            )
        except Exception as e:
            msg = f"Falha a executar scraper, site={name}, type={s_type}, err={e}"
            logger.error(msg, exc_info=True)
            return SiteRunResult(
                site_name=name,
                site_type=s_type,
                attempt=int(attempt),
                inserted=0,
                skipped=0,
                errors=1,
                ok=False,
                error_message=msg,
            )

    def _log_summary(self, results: list[SiteRunResult]) -> None:
        if not results:
            logger.info("Scraping terminou sem sites")
            return

        by_site: dict[str, list[SiteRunResult]] = {}
        for r in results:
            by_site.setdefault(r.site_name, []).append(r)

        logger.info("Resumo de scraping")
        for site_name in [str(s) for s in by_site.keys()]:
            attempts = by_site.get(site_name, [])
            last = attempts[len(attempts) - 1] if attempts else None
            if not last:
                continue
            if last.ok:
                logger.info(
                    f"Site ok, site={site_name}, attempts={len(attempts)}, inserted={last.inserted}, skipped={last.skipped}, errors={last.errors}"
                )
            else:
                logger.warning(
                    f"Site falhou, site={site_name}, attempts={len(attempts)}, inserted={last.inserted}, skipped={last.skipped}, errors={last.errors}, err={last.error_message}"
                )


if __name__ == "__main__":
    import sqlite3

    from vozdipovo_app.db.migrate import ensure_schema
    from vozdipovo_app.settings import get_settings

    settings = get_settings()
    conn = ensure_schema(str(settings.db_path))

    try:
        ctx = StageContext(
            conn=conn, app_cfg=settings.app_cfg, editorial=settings.editorial
        )
        stage = ScrapingStage(ctx=ctx)
        processed = stage.run()
        conn.commit()
        logger.info(f"Processed={processed}")
    finally:
        conn.close()
