#!src/vozdipovo_app/scrapers/base.py
from __future__ import annotations

import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from typing import Any, Dict, Iterable, Optional

from vozdipovo_app.utils.logger import get_logger


@dataclass(frozen=True, slots=True)
class ScrapeStats:
    """Estatísticas de scraping."""

    inserted: int = 0
    skipped: int = 0
    errors: int = 0

    def as_dict(self) -> Dict[str, int]:
        """Converte para dict.

        Returns:
            Dict com contadores.
        """
        return {
            "inserted": int(self.inserted),
            "skipped": int(self.skipped),
            "errors": int(self.errors),
        }


@dataclass(frozen=True, slots=True)
class InsertPayload:
    """Payload para inserção em legal_docs.

    Attributes:
        site_name: Nome do site.
        source_type: Tipo de fonte, por exemplo rss, html, bo.
        act_type: Tipo do ato.
        title: Título.
        url: Url canónica.
        url_hash: Hash da url.
        pub_date: Campo legado, quando existir.
        published_at: Campo canónico.
        summary: Resumo.
        content_text: Texto.
        raw_html: Html bruto.
        raw_payload_json: Json bruto do item para auditoria.
        fetched_at: Data de recolha.
        content_hash: Hash do texto.
    """

    site_name: str
    act_type: str
    title: str
    url: str
    source_type: str = ""
    url_hash: Optional[str] = None
    pub_date: Optional[str] = None
    published_at: Optional[str] = None
    summary: Optional[str] = None
    content_text: Optional[str] = None
    raw_html: Optional[str] = None
    raw_payload_json: Optional[str] = None
    fetched_at: Optional[str] = None
    content_hash: Optional[str] = None


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf_8")).hexdigest()


class BaseScraper(ABC):
    """Base para scrapers com assinatura estável e inserção resiliente."""

    def __init__(
        self, name: str, config: Dict[str, Any], db_conn: sqlite3.Connection
    ) -> None:
        """Inicializa o scraper.

        Args:
            name: Nome do site.
            config: Config do site.
            db_conn: Ligação SQLite.
        """
        self.name = str(name).strip()
        self.config = dict(config or {})
        self.conn = db_conn
        self.logger = get_logger(f"vozdipovo_app.scrapers.{self.name}")

    @abstractmethod
    def iter_items(self) -> Iterable[Any]:
        """Itera itens brutos.

        Returns:
            Iterable de itens.
        """
        raise NotImplementedError

    @abstractmethod
    def item_to_payload(self, item: Any) -> Optional[InsertPayload]:
        """Converte um item bruto para payload.

        Args:
            item: Item bruto.

        Returns:
            Payload ou None para ignorar.
        """
        raise NotImplementedError

    def run(self) -> Dict[str, Any]:
        """Executa scraping e insere na base.

        Returns:
            Dict com estatísticas.
        """
        inserted = 0
        skipped = 0
        errors = 0

        for item in self.iter_items():
            try:
                payload = self.item_to_payload(item)
                if payload is None:
                    skipped += 1
                    continue
                payload = self._with_debug_payload(payload, item=item)
                if self._insert_legal_doc(payload):
                    inserted += 1
                else:
                    skipped += 1
            except Exception:
                errors += 1
                self.logger.error("Falha a processar item", exc_info=True)

        return ScrapeStats(inserted=inserted, skipped=skipped, errors=errors).as_dict()

    @cached_property
    def legal_docs_columns(self) -> set[str]:
        """Obtém colunas reais da tabela legal_docs.

        Returns:
            Conjunto com nomes de colunas existentes.
        """
        rows = self.conn.execute("PRAGMA table_info(legal_docs);").fetchall()
        cols: set[str] = set()
        for r in rows:
            name = r[1] if isinstance(r, tuple) else r["name"]
            cols.add(str(name))
        return cols

    def _insert_legal_doc(self, payload: InsertPayload) -> bool:
        """Insere em legal_docs, adaptando a colunas existentes.

        Args:
            payload: Payload normalizado.

        Returns:
            True se inseriu, False se ignorou.
        """
        published = payload.published_at or payload.pub_date
        pub_date = payload.pub_date or payload.published_at

        content_text_norm = (payload.content_text or "").strip()
        content_hash = payload.content_hash or (
            _sha1(content_text_norm) if content_text_norm else None
        )
        url_hash = payload.url_hash or (
            _sha1(payload.url.strip()) if payload.url else None
        )

        source_type = str(payload.source_type or self.source_type).strip() or "unknown"

        values: Dict[str, Any] = {
            "site_name": payload.site_name,
            "source_type": source_type,
            "act_type": payload.act_type,
            "title": payload.title,
            "url": payload.url,
            "url_hash": url_hash,
            "published_at": published,
            "pub_date": pub_date,
            "summary": payload.summary,
            "content_text": content_text_norm if content_text_norm else None,
            "raw_html": payload.raw_html,
            "raw_payload_json": payload.raw_payload_json,
            "fetched_at": payload.fetched_at or _utc_now_iso(),
            "content_hash": content_hash,
        }

        cols = [c for c in values.keys() if c in self.legal_docs_columns]
        params = tuple(values[c] for c in cols)
        placeholders = ", ".join("?" for _ in cols)
        col_sql = ", ".join(cols)

        sql = f"INSERT OR IGNORE INTO legal_docs ({col_sql}) VALUES ({placeholders});"

        before = int(self.conn.total_changes)
        self.conn.execute(sql, params)
        after = int(self.conn.total_changes)
        return after > before

    @property
    def source_type(self) -> str:
        """Devolve o tipo de fonte a persistir.

        Returns:
            Tipo de fonte.
        """
        raw = str(self.config.get("source_type") or "").strip()
        if raw:
            return raw
        return self.__class__.__name__.casefold()

    def _with_debug_payload(
        self, payload: InsertPayload, *, item: Any
    ) -> InsertPayload:
        """Garante que o payload contém debug serializado quando possível.

        Args:
            payload: Payload.
            item: Item bruto.

        Returns:
            Payload atualizado.
        """
        if payload.raw_payload_json:
            return payload

        try:
            raw_json = json.dumps(item, ensure_ascii=False, default=str)
        except Exception:
            raw_json = None

        try:
            return InsertPayload(
                site_name=payload.site_name,
                act_type=payload.act_type,
                title=payload.title,
                url=payload.url,
                source_type=payload.source_type,
                url_hash=payload.url_hash,
                pub_date=payload.pub_date,
                published_at=payload.published_at,
                summary=payload.summary,
                content_text=payload.content_text,
                raw_html=payload.raw_html,
                raw_payload_json=raw_json,
                fetched_at=payload.fetched_at,
                content_hash=payload.content_hash,
            )
        except Exception:
            return payload


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

    class _DemoScraper(BaseScraper):
        def iter_items(self) -> Iterable[Any]:
            return [{"url": "https://example.com/a", "title": "A"}]

        def item_to_payload(self, item: Any) -> Optional[InsertPayload]:
            return InsertPayload(
                site_name="demo",
                act_type="news",
                title=str(item["title"]),
                url=str(item["url"]),
                published_at=_utc_now_iso(),
            )

    s = _DemoScraper("demo", {}, conn)
    s.logger.info(f"Stats={s.run()}")
