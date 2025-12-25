#!src/vozdipovo_app/scrapers/nextjs_scraper.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from vozdipovo_app.scrapers.base import BaseScraper, InsertPayload


@dataclass(frozen=True, slots=True)
class NextJsScraperConfig:
    start_url: str
    base_url: Optional[str] = None
    act_type: str = "news"
    max_pages: int = 1
    page_url_template: Optional[str] = None
    article_url_contains: Optional[str] = None
    timeout_seconds: int = 30


class NextJsScraper(BaseScraper):
    def __init__(self, name: str, config: Dict[str, Any], db_conn: Any) -> None:
        super().__init__(name, dict(config or {}), db_conn)
        self._cfg = self._parse_cfg()

    def iter_items(self) -> Iterable[Any]:
        cfg = self._cfg
        seen: set[str] = set()

        for page in range(1, int(cfg.max_pages) + 1):
            page_url = self._page_url(page)
            self.logger.info(f"Next.js list, url={page_url}")

            html = self._fetch_text(page_url)
            urls = self._extract_urls_from_next_data(html, page_url)
            if not urls:
                urls = self._extract_urls_from_html(html, page_url)

            for u in urls:
                if u in seen:
                    continue
                seen.add(u)
                yield {"url": u, "source_page": page_url}

    def item_to_payload(self, item: Any) -> Optional[InsertPayload]:
        if not isinstance(item, dict):
            return None
        url = str(item.get("url") or "").strip()
        if not url:
            return None
        if not self._is_allowed_article_url(url):
            return None

        title = url
        return InsertPayload(
            site_name=self.name,
            source_type="nextjs",
            act_type=str(self._cfg.act_type),
            title=title,
            url=url,
        )

    def _parse_cfg(self) -> NextJsScraperConfig:
        start_url = self._pick_first_str(("start_url", "list_url", "index_url", "url"))
        if not start_url:
            keys = ", ".join(sorted([str(k) for k in (self.config or {}).keys()]))
            raise ValueError(f"start_url vazio, site={self.name}, config_keys={keys}")

        base_url = str(self.config.get("base_url") or "").strip() or None
        act_type = str(self.config.get("act_type") or "news").strip()
        max_pages = int(self.config.get("max_pages") or 1)

        page_url_template = (
            str(self.config.get("page_url_template") or "").strip() or None
        )
        article_url_contains = (
            str(self.config.get("article_url_contains") or "").strip() or None
        )
        timeout_seconds = int(self.config.get("timeout_seconds") or 30)

        return NextJsScraperConfig(
            start_url=start_url,
            base_url=base_url,
            act_type=act_type,
            max_pages=max_pages,
            page_url_template=page_url_template,
            article_url_contains=article_url_contains,
            timeout_seconds=timeout_seconds,
        )

    def _pick_first_str(self, keys: tuple[str, ...]) -> str:
        for k in keys:
            v = self.config.get(k)
            s = str(v or "").strip()
            if s:
                return s
        return ""

    def _page_url(self, page: int) -> str:
        cfg = self._cfg
        if cfg.page_url_template:
            try:
                return str(cfg.page_url_template).format(page=page)
            except Exception:
                return cfg.start_url
        return cfg.start_url

    def _fetch_text(self, url: str) -> str:
        cfg = self._cfg
        r = requests.get(url, timeout=int(cfg.timeout_seconds))
        r.raise_for_status()
        return str(r.text or "")

    def _extract_urls_from_next_data(self, html: str, page_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.select_one("script#__NEXT_DATA__")
        if not script:
            return []

        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            return []

        try:
            data = json.loads(raw)
        except Exception:
            return []

        found: set[str] = set()
        self._walk_for_urls(data, found)

        resolved: list[str] = []
        for u in found:
            abs_u = self._absolutize(u, page_url)
            if abs_u:
                resolved.append(abs_u)

        return resolved

    def _extract_urls_from_html(self, html: str, page_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        hrefs = [a.get("href") for a in soup.select("a[href]")]
        found = [str(h).strip() for h in hrefs if isinstance(h, str) and str(h).strip()]
        resolved: list[str] = []
        for u in found:
            abs_u = self._absolutize(u, page_url)
            if abs_u:
                resolved.append(abs_u)
        return resolved

    def _walk_for_urls(self, obj: Any, out: set[str]) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and self._looks_like_url(v):
                    out.add(v)
                if (
                    isinstance(k, str)
                    and k.lower() in {"href", "aspath", "path", "url"}
                    and isinstance(v, str)
                ):
                    out.add(v)
                self._walk_for_urls(v, out)
            return
        if isinstance(obj, list):
            for x in obj:
                self._walk_for_urls(x, out)
            return

    def _looks_like_url(self, s: str) -> bool:
        t = str(s or "").strip()
        if not t:
            return False
        if t.startswith("http://") or t.startswith("https://"):
            return True
        if t.startswith("/"):
            return True
        return False

    def _absolutize(self, url: str, page_url: str) -> str:
        u = str(url or "").strip()
        if not u:
            return ""
        if u.startswith("http://") or u.startswith("https://"):
            return u
        base = self._cfg.base_url or self._origin(page_url)
        return urljoin(base, u)

    def _origin(self, u: str) -> str:
        p = urlparse(u)
        if not p.scheme or not p.netloc:
            return ""
        return f"{p.scheme}://{p.netloc}"

    def _is_allowed_article_url(self, url: str) -> bool:
        needle = self._cfg.article_url_contains
        if not needle:
            return True
        return needle in url


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
          url TEXT NOT NULL UNIQUE,
          url_hash TEXT,
          pub_date TEXT,
          published_at TEXT,
          summary TEXT,
          content_text TEXT,
          raw_html TEXT,
          fetched_at TEXT,
          content_hash TEXT,
          created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )

    s = NextJsScraper(
        "demo_nextjs",
        {
            "start_url": "https://example.com",
            "max_pages": 1,
            "article_url_contains": "/noticia",
        },
        conn,
    )
    s.logger.info(f"Items={list(s.iter_items())[:3]}")
