#!src/vozdipovo_app/db/repos/legal_docs_repo.py
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


@dataclass(frozen=True, slots=True)
class InsertResult:
    inserted: bool
    reason: str


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf_8")).hexdigest()


class LegalDocsRepo:
    """Repo para tabela legal_docs com dedupe e upsert leve."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def ensure_columns(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_docs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              site_name TEXT NOT NULL,
              act_type TEXT NOT NULL,
              title TEXT NOT NULL,
              url TEXT NOT NULL UNIQUE,
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
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_legal_docs_site_name ON legal_docs(site_name);"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_legal_docs_published_at ON legal_docs(published_at);"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_legal_docs_content_hash ON legal_docs(content_hash);"
        )

    def has_url(self, url: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM legal_docs WHERE url = ? LIMIT 1;", (url,)
        ).fetchone()
        return row is not None

    def insert_doc(
        self,
        *,
        site_name: str,
        act_type: str,
        title: str,
        url: str,
        published_at: Optional[str],
        summary: Optional[str],
        content_text: Optional[str],
        raw_html: Optional[str],
        fetched_at: Optional[str] = None,
    ) -> InsertResult:
        content_text_norm = (content_text or "").strip()
        content_hash = _sha1(content_text_norm) if content_text_norm else None

        if self.has_url(url):
            return InsertResult(inserted=False, reason="duplicate_url")

        if content_hash:
            row = self._conn.execute(
                "SELECT 1 FROM legal_docs WHERE content_hash = ? LIMIT 1;",
                (content_hash,),
            ).fetchone()
            if row is not None:
                return InsertResult(inserted=False, reason="duplicate_content_hash")

        self._conn.execute(
            """
            INSERT INTO legal_docs(
              site_name, act_type, title, url, published_at, summary,
              content_text, raw_html, fetched_at, content_hash, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                str(site_name),
                str(act_type),
                str(title),
                str(url),
                published_at,
                summary,
                content_text_norm if content_text_norm else None,
                raw_html,
                fetched_at or _utc_now_iso(),
                content_hash,
                _utc_now_iso(),
            ),
        )
        return InsertResult(inserted=True, reason="inserted")

    def count_recent_by_site(self, site_name: str, since_iso: str) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM legal_docs
            WHERE site_name = ? AND created_at >= ?;
            """,
            (site_name, since_iso),
        ).fetchone()
        if row is None:
            return 0
        return int(row["c"] if isinstance(row, sqlite3.Row) else row[0])
