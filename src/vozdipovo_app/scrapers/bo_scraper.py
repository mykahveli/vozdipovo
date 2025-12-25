#!src/vozdipovo_app/scrapers/bo_scraper.py
from __future__ import annotations

import html
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from vozdipovo_app.scrapers.base import BaseScraper, InsertPayload


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _norm_no_accents(text: str) -> str:
    raw = str(text or "")
    nfkd = unicodedata.normalize("NFKD", raw)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_text.casefold()


@dataclass(frozen=True, slots=True)
class BOScraperConfig:
    base_url: str
    start_url: str
    list_item_selector: str
    link_selector: str
    next_page_selector: str
    max_pages: int
    throttle_seconds: float
    timeout_seconds: int
    default_act_type: str
    default_entity: str


class BOScraper(BaseScraper):
    def __init__(self, name: str, config: Dict[str, Any], db_conn: Any) -> None:
        super().__init__(name, dict(config or {}), db_conn)
        self._cfg = self._parse_cfg()
        self._session = requests.Session()
        self._last_request_at: Optional[float] = None
        self._date_re = self._build_date_re()
        self._b64_re = self._build_b64_re()
        self._blacklist_terms = tuple(self._build_blacklist_terms())

    def iter_items(self) -> Iterable[Any]:
        cfg = self._cfg
        url = cfg.start_url
        seen_list_pages: set[str] = set()

        for page_index in range(int(cfg.max_pages)):
            if url in seen_list_pages:
                self.logger.warning(f"Loop detetado na listagem, url={url}")
                break
            seen_list_pages.add(url)

            soup = self._fetch_soup(url)
            cards = soup.select(cfg.list_item_selector)
            self.logger.info(
                f"BO listagem, page={page_index + 1}, url={url}, cards={len(cards)}"
            )

            for card in cards:
                link_tag = card.select_one(cfg.link_selector)
                href = link_tag.get("href") if link_tag else None
                if not isinstance(href, str) or not href.strip():
                    continue

                edition_url = urljoin(cfg.base_url, href)
                pub_date_hint = self._extract_date_from_text(card.get_text(" "))
                yield from self._iter_edition(edition_url, pub_date_hint)

            next_url = self._next_list_url(soup)
            if not next_url:
                break
            url = next_url

    def item_to_payload(self, item: Any) -> Optional[InsertPayload]:
        if not isinstance(item, dict):
            return None

        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url or not title:
            return None

        pub_date = str(item.get("pub_date") or "").strip() or None
        summary = str(item.get("summary") or "").strip() or None
        content_text = str(item.get("content_text") or "").strip() or None
        raw_html = str(item.get("raw_html") or "").strip() or None
        act_type = str(item.get("act_type") or self._cfg.default_act_type).strip()

        return InsertPayload(
            site_name=self.name,
            source_type="bo",
            act_type=act_type,
            title=title,
            url=url,
            pub_date=pub_date,
            published_at=pub_date,
            summary=summary,
            content_text=content_text,
            raw_html=raw_html,
            fetched_at=_utc_now_iso(),
        )

    def _iter_edition(
        self, edition_url: str, pub_date_fallback: Optional[str]
    ) -> Iterable[Dict[str, Any]]:
        soup = self._fetch_soup(edition_url)
        pub_date = self._extract_date_from_text(soup.get_text(" ")) or pub_date_fallback

        act_links = soup.select("a[href^='/Bulletins/View/']")
        self.logger.info(
            f"BO edicao, url={edition_url}, atos={len(act_links)}, pub_date={pub_date}"
        )

        for link_tag in act_links:
            href = link_tag.get("href") if link_tag else None
            if not isinstance(href, str) or not href.strip():
                continue

            act_url = urljoin(self._cfg.base_url, href)
            title_guess = str(link_tag.get_text(" ", strip=True) or "").strip()

            if self._is_blacklisted(title_guess):
                continue

            act_item = self._fetch_act(act_url, pub_date, edition_url, title_guess)
            if act_item is not None:
                yield act_item

    def _fetch_act(
        self,
        act_url: str,
        pub_date: Optional[str],
        edition_url: str,
        title_guess: str,
    ) -> Optional[Dict[str, Any]]:
        soup = self._fetch_soup(act_url)

        title_node = soup.select_one(".card-header .w-75")
        title = (
            str(title_node.get_text(" ", strip=True) or "").strip()
            if title_node
            else title_guess
        )

        entity_node = soup.select_one("a[href^='/Bulletins?Entity=']")
        entity = (
            str(entity_node.get_text(" ", strip=True) or "").strip()
            if entity_node
            else self._cfg.default_entity
        )

        type_node = soup.select_one("a[href^='/Bulletins?Type=']")
        act_type = (
            str(type_node.get_text(" ", strip=True) or "").strip()
            if type_node
            else self._cfg.default_act_type
        )

        summary_node = soup.select_one("label[for='Summary'] ~ p")
        summary = (
            str(summary_node.get_text(" ", strip=True) or "").strip()
            if summary_node
            else None
        )

        text = self._extract_main_text(soup)
        clean_html = self._b64_re.sub("[img_removed]", str(soup))

        return {
            "url": act_url,
            "title": title,
            "pub_date": pub_date,
            "edition_url": edition_url,
            "entity": entity,
            "act_type": act_type,
            "summary": summary,
            "content_text": text,
            "raw_html": clean_html,
        }

    def _extract_main_text(self, soup: BeautifulSoup) -> str:
        content_node = soup.select_one("content[data-content]")
        if content_node:
            data_content = content_node.get("data-content")
            if isinstance(data_content, str) and data_content.strip():
                raw_html = html.unescape(data_content)
                return BeautifulSoup(raw_html, "lxml").get_text("\n", strip=True)

        ql_node = soup.select_one("div.ql-editor.client-mode")
        if ql_node:
            return ql_node.get_text("\n", strip=True)

        try:
            from readability import Document

            doc = Document(str(soup))
            main_html = doc.summary()
            if isinstance(main_html, str) and main_html.strip():
                return BeautifulSoup(main_html, "lxml").get_text("\n", strip=True)
        except Exception:
            pass

        return soup.get_text("\n", strip=True)

    def _extract_date_from_text(self, text: str) -> Optional[str]:
        m = self._date_re.search(str(text or ""))
        return m.group(1) if m else None

    def _next_list_url(self, soup: BeautifulSoup) -> str:
        sel = str(self._cfg.next_page_selector or "").strip()
        if not sel:
            return ""
        a = soup.select_one(sel)
        href = a.get("href") if a else None
        if not isinstance(href, str) or not href.strip():
            return ""
        return urljoin(self._cfg.base_url, href)

    def _fetch_soup(self, url: str) -> BeautifulSoup:
        self._throttle()
        timeout = int(self._cfg.timeout_seconds)
        r = self._session.get(url, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(str(r.text or ""), "lxml")

    def _throttle(self) -> None:
        delay = float(self._cfg.throttle_seconds)
        if delay <= 0:
            return
        now = time.time()
        last = self._last_request_at
        if last is not None:
            elapsed = now - last
            if elapsed < delay:
                time.sleep(delay - elapsed)
        self._last_request_at = time.time()

    def _parse_cfg(self) -> BOScraperConfig:
        raw = self.config or {}
        base_url = str(raw.get("base_url") or "").strip()
        start_url = str(raw.get("start_url") or raw.get("listing_url") or "").strip()
        if not base_url or not start_url:
            raise ValueError(f"Config invalida, site={self.name}")

        list_item_selector = str(raw.get("list_item_selector") or "div.card").strip()
        link_selector = str(raw.get("link_selector") or "a[href]").strip()
        next_page_selector = str(raw.get("next_page_selector") or "").strip()

        max_pages = int(raw.get("max_pages") or 3)
        throttle_seconds = float(raw.get("throttle_seconds") or 0.0)
        timeout_seconds = int(raw.get("timeout_seconds") or 30)

        default_act_type = str(raw.get("default_act_type") or "legal").strip()
        default_entity = str(raw.get("default_entity") or "").strip()

        return BOScraperConfig(
            base_url=base_url,
            start_url=start_url,
            list_item_selector=list_item_selector,
            link_selector=link_selector,
            next_page_selector=next_page_selector,
            max_pages=max_pages,
            throttle_seconds=throttle_seconds,
            timeout_seconds=timeout_seconds,
            default_act_type=default_act_type,
            default_entity=default_entity,
        )

    def _is_blacklisted(self, title: str) -> bool:
        t = _norm_no_accents(str(title or ""))
        if not t:
            return False
        for term in self._blacklist_terms:
            if term and term in t:
                return True
        return False

    def _build_blacklist_terms(self) -> Iterable[str]:
        terms = [
            "acordo",
            "protocolo",
            "acordo colectivo de trabalho",
            "acordo coletivo de trabalho",
            "acordo de adesao",
            "contrato",
            "contrato de gestao",
            "contrato de prestacao de servico",
            "contrato de prestacao de servicos",
            "contrato de avenca",
            "contrato de trabalho",
            "rescisao de contrato de trabalho",
            "estatuto",
            "fundacao",
            "cooperativa",
            "organizacoes religiosas",
            "confecoes das organizacoes religiosas",
            "convocatoria",
            "ata",
            "anuncio",
            "anuncio de concurso",
            "anuncio de concurso urgente",
            "anuncio de procedimento",
            "aviso",
            "aviso de prorrogacao de prazo",
            "aviso do banco de cabo verde",
            "comunicacao",
            "instrucao",
            "recomendacao",
            "louvor",
            "declaracao",
            "declaracao de rectificacao",
            "declaracao de retificacao",
            "declaracao de rectificacao de anuncio",
            "retificacao",
            "republicacao",
            "anulacao de publicacao",
            "extracto de despacho",
            "extrato de despacho",
            "extrato da deliberacao",
            "extrato do despacho conjunto",
            "extrato do contrato de gestao",
            "extrato do contrato de trabalho",
            "extrato de publicacao da associacao",
            "extrato de publicacao de associacao",
            "extrato de publicacao da sociedade",
            "extrato de publicacao de sociedade",
            "relatorio",
            "mapa",
            "mapa oficial",
            "listagem",
            "balanco",
            "balancetes",
        ]
        return [_norm_no_accents(t) for t in terms]

    def _build_date_re(self) -> re.Pattern[str]:
        h = chr(45)
        pat = (
            rf"\b(\d{{1,2}}/\d{{1,2}}/\d{{4}}|"
            rf"\d{{4}}{h}\d{{2}}{h}\d{{2}}|"
            rf"\d{{2}}{h}\d{{2}}{h}\d{{4}})\b"
        )
        return re.compile(pat)

    def _build_b64_re(self) -> re.Pattern[str]:
        h = chr(45)
        pat = (
            rf"data\s*:\s*image/[a-z0-9.+{h}]+;base64,"
            rf"[A-Za-z0-9+/=\s]+?(?=[\"\')>])"
        )
        return re.compile(pat, re.IGNORECASE | re.DOTALL)


if __name__ == "__main__":
    import sqlite3

    conn = sqlite3.connect(":memory:")
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

    s = BOScraper(
        "bo_cv",
        {
            "base_url": "https://boe.incv.cv",
            "start_url": "https://boe.incv.cv/Bulletins",
            "list_item_selector": "div.card.mb-2",
            "link_selector": "a[href^='/Bulletins/Details/']",
            "next_page_selector": "ul.pagination li a[aria-label='Página seguinte']",
            "max_pages": 1,
            "throttle_seconds": 0.0,
        },
        conn,
    )

    try:
        stats = s.run()
        s.logger.info(f"Stats={stats}")
    except Exception:
        s.logger.error("Falha em run", exc_info=True)
