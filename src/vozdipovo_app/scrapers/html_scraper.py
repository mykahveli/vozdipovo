#!src/vozdipovo_app/scrapers/html_scraper.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import requests
from bs4 import BeautifulSoup

from vozdipovo_app.scrapers.base import BaseScraper, InsertPayload


@dataclass(frozen=True, slots=True)
class HtmlScraperConfig:
    """Config de scraping html."""

    start_url: str
    act_type: str = "legal"
    max_pages: int = 1


class HtmlScraper(BaseScraper):
    """Scraper html genérico."""

    def __init__(
        self, name: str, config: Dict[str, Any], db_conn: sqlite3.Connection
    ) -> None:
        super().__init__(name, dict(config or {}), db_conn)
        self._cfg = self._parse_cfg()

    def iter_items(self) -> Iterable[Any]:
        url = str(self._cfg.start_url).strip()
        self.logger.info(f"Html list, url={url}")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        links = [a.get("href") for a in soup.select("a[href]")]
        return [x for x in links if isinstance(x, str) and x.strip()]

    def item_to_payload(self, item: Any) -> Optional[InsertPayload]:
        url = str(item or "").strip()
        if not url:
            return None
        title = url
        return InsertPayload(
            site_name=self.name,
            source_type="html",
            act_type=str(self._cfg.act_type),
            title=title,
            url=url,
        )

    def _parse_cfg(self) -> HtmlScraperConfig:
        start_url = self._pick_first_str(
            keys=("start_url", "list_url", "index_url", "bulletins_url", "url"),
        )
        if not start_url:
            keys = ", ".join(sorted([str(k) for k in (self.config or {}).keys()]))
            raise ValueError(f"start_url vazio, site={self.name}, config_keys={keys}")

        return HtmlScraperConfig(
            start_url=start_url,
            act_type=str(self.config.get("act_type") or "legal").strip(),
            max_pages=int(self.config.get("max_pages") or 1),
        )

    def _pick_first_str(self, *, keys: tuple[str, ...]) -> str:
        for k in keys:
            v = self.config.get(k)
            s = str(v or "").strip()
            if s:
                return s
        return ""


if __name__ == "__main__":
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE legal_docs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          site_name TEXT NOT NULL,
          act_type TEXT NOT NULL,
          title TEXT NOT NULL,
          url TEXT NOT NULL UNIQUE
        );
        """
    )
    s = HtmlScraper("demo_html", {"list_url": "https://example.com"}, conn)
    s.logger.info(f"Start={s._cfg.start_url}")
