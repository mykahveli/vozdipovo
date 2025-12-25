#!filepath: src/vozdipovo_app/modules/revision_stage.py
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import List, Sequence

from vozdipovo_app.article_reviser import revise_article
from vozdipovo_app.modules.base import Stage, StageContext
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


def _candidates(conn: sqlite3.Connection, limit: int) -> Sequence[sqlite3.Row]:
    return conn.execute(
        """
        SELECT na.*, ld.site_name, ld.act_type
        FROM news_articles na
        JOIN legal_docs ld ON ld.id = na.legal_doc_id
        WHERE na.review_status = 'GENERATED'
        ORDER BY na.final_score DESC
        LIMIT ?;
        """.strip(),
        (int(limit),),
    ).fetchall()


def _loads_list(s: str) -> List[str]:
    try:
        v = json.loads(s or "[]")
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []
    except Exception:
        return []


@dataclass(frozen=True, slots=True)
class RevisionStage(Stage):
    """Editor stage, revises and validates the draft."""

    ctx: StageContext
    limit: int

    def run(self) -> int:
        conn = self.ctx.conn
        conn.row_factory = sqlite3.Row
        rows = _candidates(conn, limit=int(self.limit))
        if not rows:
            return 0

        updated = 0
        for r in rows:
            legal_doc_id = int(r["legal_doc_id"])
            title = str(r["titulo"] or "")
            body_md = str(r["corpo_md"] or "")
            keywords = str(r["keywords"] or "")
            categoria = str(r["categoria_tematica"] or "")
            subcategoria = str(r["subcategoria"] or "")
            site_name = str(r["site_name"] or "")
            act_type = str(r["act_type"] or "")
            factos = _loads_list(str(r["reporter_facts_json"] or "[]"))

            try:
                rev = revise_article(
                    title=title,
                    text_md=body_md,
                    keywords=keywords,
                    site_name=site_name,
                    act_type=act_type,
                    categoria_tematica=categoria,
                    subcategoria=subcategoria,
                    factos_nucleares=factos,
                )

                if rev.revision_status != "OK":
                    conn.execute(
                        """
                        UPDATE news_articles
                        SET review_status='ERROR',
                            review_error=?,
                            reviewed_at=datetime('now')
                        WHERE legal_doc_id=?;
                        """.strip(),
                        (str(rev.revision_error or "")[:900], legal_doc_id),
                    )
                    conn.commit()
                    continue

                conn.execute(
                    """
                    UPDATE news_articles
                    SET titulo=?,
                        corpo_md=?,
                        keywords=?,
                        categoria_tematica=?,
                        subcategoria=?,
                        editor_comments=?,
                        editor_checklist_json=?,
                        reviewed_by_model=?,
                        review_error='',
                        review_status='REVIEWED',
                        reviewed_at=datetime('now')
                    WHERE legal_doc_id=?;
                    """.strip(),
                    (
                        str(rev.titulo_revisto or "")[:220],
                        str(rev.texto_completo_md_revisto or ""),
                        ", ".join([k for k in rev.keywords_revistas if str(k).strip()])[
                            :800
                        ],
                        str(rev.categoria_tematica or "")[:60],
                        str(rev.subcategoria or "")[:80],
                        str(rev.comentarios_edicao or "")[:900],
                        str(rev.checklist_json or "{}")[:2000],
                        str(rev.revision_model_used or "")[:200],
                        legal_doc_id,
                    ),
                )
                conn.commit()
                updated += 1
            except Exception as e:
                conn.rollback()
                logger.error(f"❌ Editor falhou, legal_doc_id={legal_doc_id}, erro={e}")

        return updated
