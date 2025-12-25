#!src/vozdipovo_app/scrapers/rss_scraper.py
from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, Mapping, Optional
from xml.etree import ElementTree

import requests

from vozdipovo_app.scrapers.base import BaseScraper, InsertPayload


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_any_date_to_iso(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    if not raw:
        return None

    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return _to_iso(dt)
    except Exception:
        pass

    try:
        dt2 = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt2.tzinfo is None:
            dt2 = dt2.replace(tzinfo=timezone.utc)
        return _to_iso(dt2)
    except Exception:
        return None


def _safe_text(node: Optional[ElementTree.Element]) -> str:
    if node is None:
        return ""
    return str(node.text or "").strip()


def _parse_feed_xml(url: str, *, timeout_seconds: int) -> list[dict[str, str]]:
    r = requests.get(url, timeout=int(timeout_seconds))
    r.raise_for_status()
    xml_text = str(r.text or "")

    root = ElementTree.fromstring(xml_text)

    items: list[dict[str, str]] = []

    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            title = _safe_text(item.find("title"))
            link = _safe_text(item.find("link"))
            pub_date = _safe_text(item.find("pubDate"))
            items.append({"title": title, "link": link, "published": pub_date})
        return items

    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.findall(f"{ns}entry"):
        title = _safe_text(entry.find(f"{ns}title"))
        link = ""
        for ln in entry.findall(f"{ns}link"):
            rel = str(ln.attrib.get("rel") or "").strip()
            href = str(ln.attrib.get("href") or "").strip()
            if not href:
                continue
            if not rel or rel == "alternate":
                link = href
                break
        published = _safe_text(entry.find(f"{ns}published")) or _safe_text(
            entry.find(f"{ns}updated")
        )
        items.append({"title": title, "link": link, "published": published})

    return items


def _parse_entries(url: str, *, timeout_seconds: int) -> list[Any]:
    try:
        import feedparser

        feed = feedparser.parse(url)
        return list(getattr(feed, "entries", []) or [])
    except Exception:
        return _parse_feed_xml(url, timeout_seconds=timeout_seconds)


def _entry_get(entry: Any, key: str) -> str:
    if isinstance(entry, dict):
        return str(entry.get(key) or "").strip()
    return str(getattr(entry, key, "") or "").strip()


def _entry_published_iso(entry: Any) -> Optional[str]:
    if isinstance(entry, dict):
        return _parse_any_date_to_iso(_entry_get(entry, "published"))

    for k in ("published", "updated"):
        iso = _parse_any_date_to_iso(_entry_get(entry, k))
        if iso:
            return iso

    for k in ("published_parsed", "updated_parsed"):
        t = getattr(entry, k, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                continue

    return None


@dataclass(frozen=True, slots=True)
class RssScraperConfig:
    """Config do scraper RSS.

    Attributes:
        feed_url: URL do feed.
        max_entries: Máximo de entradas por corrida.
        max_age_hours: Janela máxima, em horas.
        drop_if_no_pub_date: Se descarta entradas sem data.
        act_type: Tipo do registo.
        timeout_seconds: Timeout http.
    """

    feed_url: str
    max_entries: int = 60
    max_age_hours: int = 72
    drop_if_no_pub_date: bool = True
    act_type: str = "news"
    timeout_seconds: int = 30


class RssScraper(BaseScraper):
    """Scraper RSS com fallback xml, compatível com BaseScraper."""

    def __init__(self, name: str, config: Dict[str, Any], db_conn: Any) -> None:
        super().__init__(name, dict(config or {}), db_conn)
        self._cfg = self._parse_cfg()

    def iter_items(self) -> Iterable[Any]:
        cfg = self._cfg
        self.logger.info(f"RSS fetch, url={cfg.feed_url}")

        entries = _parse_entries(cfg.feed_url, timeout_seconds=int(cfg.timeout_seconds))
        self.logger.info(f"RSS entries, count={len(entries)}")

        cutoff = operator.sub(_utc_now(), timedelta(hours=int(cfg.max_age_hours)))

        kept: list[Any] = []
        for e in entries[: int(cfg.max_entries)]:
            published_iso = _entry_published_iso(e)
            if cfg.drop_if_no_pub_date and not published_iso:
                continue
            if published_iso:
                try:
                    dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except Exception:
                    pass
            kept.append(e)

        return kept

    def item_to_payload(self, item: Any) -> Optional[InsertPayload]:
        url = _entry_get(item, "link")
        title = _entry_get(item, "title")
        if not url or not title:
            return None

        published_iso = _entry_published_iso(item)
        summary = _entry_get(item, "summary") or None

        return InsertPayload(
            site_name=self.name,
            source_type="rss",
            act_type=str(self._cfg.act_type),
            title=title,
            url=url,
            published_at=published_iso,
            summary=summary,
            fetched_at=_to_iso(_utc_now()),
        )

    def _parse_cfg(self) -> RssScraperConfig:
        raw: Mapping[str, Any] = self.config or {}
        feed_url = str(raw.get("feed_url") or "").strip()
        if not feed_url:
            raise ValueError(f"RSS feed_url vazio, site={self.name}")

        return RssScraperConfig(
            feed_url=feed_url,
            max_entries=int(raw.get("max_entries") or 60),
            max_age_hours=int(raw.get("max_age_hours") or 72),
            drop_if_no_pub_date=bool(
                raw.get("drop_if_no_pub_date")
                if raw.get("drop_if_no_pub_date") is not None
                else True
            ),
            act_type=str(raw.get("act_type") or "news").strip(),
            timeout_seconds=int(raw.get("timeout_seconds") or 30),
        )


if __name__ == "__main__":
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE legal_docs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          site_name TEXT NOT NULL,
          source_type TEXT NOT NULL,
          url TEXT NOT NULL UNIQUE,
          url_hash TEXT,
          act_type TEXT,
          title TEXT,
          pub_date TEXT,
          published_at TEXT,
          summary TEXT,
          content_text TEXT,
          raw_html TEXT,
          raw_payload_json TEXT,
          fetched_at TEXT
        );
        """
    )

    s = RssScraper(
        "demo_rss",
        {"feed_url": "https://www.governo.cv/noticias/feed", "max_entries": 5},
        conn,
    )

    try:
        stats = s.run()
        s.logger.info(f"Stats={stats}")
    except Exception:
        s.logger.error("Falha em run", exc_info=True)
