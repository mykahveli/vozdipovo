#!filepath: src/vozdipovo_app/modules/publishing_stage.py
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import List, Optional

from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.modules.stage import Stage, StageContext
from vozdipovo_app.utils.logger import get_logger
from vozdipovo_app.wordpress.publisher import upsert_post

logger = get_logger(__name__)


def _candidates(conn: sqlite3.Connection, limit: int) -> List[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT
          a.id,
          a.legal_doc_id,
          a.titulo,
          a.corpo_md,
          a.keywords,
          a.keywords_json,
          a.categoria_tematica,
          a.subcategoria,
          a.wp_post_id,
          a.review_status,
          a.publishing_status
        FROM news_articles a
        WHERE a.review_status = 'SUCCESS'
          AND COALESCE(a.publishing_status, 'PENDING') != 'SUCCESS'
          AND a.titulo IS NOT NULL
          AND TRIM(a.titulo) != ''
        ORDER BY a.score_editorial DESC, a.final_score DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()


def _mark_published(
    conn: sqlite3.Connection, row_id: int, post_id: int, url: str
) -> None:
    conn.execute(
        """
        UPDATE news_articles
        SET publishing_status='SUCCESS',
            published_at=datetime('now'),
            wp_post_id=?,
            wp_url=?,
            wp_error=NULL,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (int(post_id), str(url or "")[:800], int(row_id)),
    )
    conn.commit()


def _mark_failed(conn: sqlite3.Connection, row_id: int, err: str) -> None:
    conn.execute(
        """
        UPDATE news_articles
        SET publishing_status='FAILED',
            wp_error=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (str(err)[:900], int(row_id)),
    )
    conn.commit()


def _keywords_list(row: sqlite3.Row) -> List[str]:
    raw = str(row["keywords_json"] or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    legacy = str(row["keywords"] or "").strip()
    if not legacy:
        return []
    parts = [p.strip() for p in legacy.split(",") if p.strip()]
    out: List[str] = []
    seen: set[str] = set()
    for p in parts:
        k = p.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


@dataclass(frozen=True, slots=True)
class PublishingStage(Stage):
    ctx: StageContext
    limit: int
    throttle_seconds: float

    def run(self) -> int:
        cfg = get_editorial_config()
        rows = _candidates(self.ctx.conn, self.limit)
        if not rows:
            logger.info("ℹ️ Nenhum artigo para publicar.")
            return 0

        published = 0
        seen_title_keys: set[str] = set()

        for r in rows:
            row_id = int(r["id"])
            title = str(r["titulo"] or "").strip()
            body = str(r["corpo_md"] or "").strip()
            categoria = str(r["categoria_tematica"] or "Geral").strip() or "Geral"
            subcategoria = str(r["subcategoria"] or "").strip()
            wp_post_id = int(r["wp_post_id"] or 0)

            title_key = " ".join([t.casefold() for t in title.split() if t.strip()])
            if title_key in seen_title_keys:
                continue
            seen_title_keys.add(title_key)

            try:
                keywords = _keywords_list(r)
                post_id, post_url = upsert_post(
                    title=title,
                    content_md=body,
                    keywords=keywords,
                    categoria_tematica=categoria,
                    subcategoria=subcategoria,
                    existing_post_id=wp_post_id if wp_post_id > 0 else None,
                    default_status=str(cfg.wordpress.default_status),
                )
                _mark_published(self.ctx.conn, row_id, int(post_id), str(post_url))
                published += 1
            except Exception as e:
                _mark_failed(self.ctx.conn, row_id, str(e))
            time.sleep(float(self.throttle_seconds))

        return published
