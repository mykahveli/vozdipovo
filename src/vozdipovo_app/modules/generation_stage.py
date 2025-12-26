#!src/vozdipovo_app/modules/generation_stage.py
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from vozdipovo_app.config_editorial import get_editorial_config
from vozdipovo_app.news_pipeline import generate_one
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


_STOPWORDS = {
    "para",
    "pelo",
    "pela",
    "como",
    "quando",
    "onde",
    "porque",
    "tambem",
    "também",
}


def _candidates(
    conn: sqlite3.Connection, significance_threshold: float, limit: int
) -> Sequence[sqlite3.Row]:
    threshold = float(significance_threshold or 0.0)
    if threshold > 0.0:
        return conn.execute(
            """
            SELECT
              a.legal_doc_id,
              d.site_name,
              d.act_type
            FROM news_articles a
            JOIN legal_docs d ON d.id = a.legal_doc_id
            WHERE a.decision = 'WRITE'
              AND a.final_score >= ?
              AND (
                  a.review_status = 'JUDGED'
                  OR a.review_status = 'FAILED'
                  OR a.review_status IS NULL
                  OR a.review_status = ''
              )
              AND (a.corpo_md IS NULL OR a.corpo_md = '')
            ORDER BY a.score_editorial DESC, a.final_score DESC
            LIMIT ?;
            """.strip(),
            (threshold, int(limit)),
        ).fetchall()

    return conn.execute(
        """
        SELECT
          a.legal_doc_id,
          d.site_name,
          d.act_type
        FROM news_articles a
        JOIN legal_docs d ON d.id = a.legal_doc_id
        WHERE a.decision = 'WRITE'
          AND (
              a.review_status = 'JUDGED'
              OR a.review_status = 'FAILED'
              OR a.review_status IS NULL
              OR a.review_status = ''
          )
          AND (a.corpo_md IS NULL OR a.corpo_md = '')
        ORDER BY a.score_editorial DESC, a.final_score DESC
        LIMIT ?;
        """.strip(),
        (int(limit),),
    ).fetchall()


def _coerce_list_str(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


def _coerce_text(v: Any) -> str:
    return str(v or "").strip()


def _tokens(text: str) -> Iterable[str]:
    for m in re.finditer(r"[0-9A-Za-zÀ-ÿ]{4,}", (text or "").casefold()):
        t = m.group(0)
        if t in _STOPWORDS:
            continue
        yield t


def _overlap_stats(source: str, generated: str) -> tuple[int, float]:
    source_set = set(_tokens(source))
    gen_set = set(_tokens(generated))
    if not source_set:
        return 0, 0.0
    common = source_set.intersection(gen_set)
    ratio = float(len(common)) / float(len(source_set))
    return len(common), ratio


def _source_text(conn: sqlite3.Connection, legal_doc_id: int) -> str:
    row = conn.execute(
        "SELECT title, summary, content_text, url, pub_date, published_at FROM legal_docs WHERE id=?",
        (int(legal_doc_id),),
    ).fetchone()
    if not row:
        return ""
    parts = [
        str(row["title"] or ""),
        str(row["summary"] or ""),
        str(row["content_text"] or ""),
    ]
    merged = "\n\n".join([p.strip() for p in parts if str(p).strip()]).strip()
    url = str(row["url"] or "").strip()
    pub_date = str(row["pub_date"] or row["published_at"] or "").strip()
    if url:
        merged = f"{merged}\n\nURL: {url}".strip()
    if pub_date:
        merged = f"{merged}\n\nDATA: {pub_date}".strip()
    return merged


@dataclass(frozen=True, slots=True)
class GenerationStage:
    """Gera drafts (Writer) e persiste em news_articles."""

    ctx: Any
    significance_threshold: float
    limit: int

    def _quality(self) -> tuple[int, int, float]:
        q = get_editorial_config().quality
        return (
            int(q.min_source_chars),
            int(q.min_overlap_tokens),
            float(q.min_overlap_ratio),
        )

    def run(self) -> int:
        conn = self.ctx.conn
        cfg = self.ctx.app_cfg

        prompt_path = str(
            cfg.get("paths", {}).get("prompt", "configs/prompts/reporter.md")
        )
        rows = _candidates(conn, self.significance_threshold, self.limit)
        if not rows:
            logger.info("Nenhum artigo elegível para redação.")
            return 0

        min_source_chars, min_overlap_tokens, min_overlap_ratio = self._quality()
        done = 0

        for r in rows:
            legal_doc_id = int(r["legal_doc_id"])
            site_name = str(r["site_name"] or "").strip()
            act_type = str(r["act_type"] or "").strip()

            try:
                source = _source_text(conn, legal_doc_id)
                if len(source) < min_source_chars:
                    raise RuntimeError(
                        f"Fonte curta, legal_doc_id={legal_doc_id}, chars={len(source)}"
                    )

                draft = generate_one(
                    cfg,
                    legal_doc_id,
                    prompt_path,
                    conn=conn,
                    rotator=getattr(self.ctx, "rotator", None),
                )

                draft_title = _coerce_text(draft.get("titulo"))
                draft_body = _coerce_text(
                    draft.get("texto_completo_md") or draft.get("corpo_md")
                )
                factos = _coerce_list_str(draft.get("factos_nucleares"))
                fontes = _coerce_list_str(draft.get("fontes_mencionadas"))
                keywords_list = _coerce_list_str(draft.get("keywords"))
                categoria = _coerce_text(draft.get("categoria_tematica"))
                subcategoria = _coerce_text(draft.get("subcategoria"))

                if not draft_title or not draft_body:
                    raise RuntimeError("Draft incompleto (titulo/corpo).")

                common, ratio = _overlap_stats(source, f"{draft_title}\n{draft_body}")
                if common < min_overlap_tokens or ratio < min_overlap_ratio:
                    raise RuntimeError(
                        f"Baixa fidelidade, common={common}, ratio={ratio:.4f}"
                    )

                conn.execute(
                    """
                    UPDATE news_articles
                    SET titulo=?,
                        corpo_md=?,
                        keywords=?,
                        keywords_json=?,
                        categoria_tematica=?,
                        subcategoria=?,
                        reporter_payload_json=?,
                        reporter_factos_json=?,
                        reporter_fontes_json=?,
                        reviewed_by_model=?,
                        review_error='',
                        review_status='GENERATED',
                        reviewed_at=datetime('now'),
                        updated_at=datetime('now')
                    WHERE legal_doc_id=?;
                    """.strip(),
                    (
                        draft_title[:220],
                        draft_body,
                        ", ".join(keywords_list)[:800],
                        json.dumps(keywords_list, ensure_ascii=False)[:2000],
                        categoria[:60],
                        subcategoria[:80],
                        str(draft.get("reporter_payload_json") or "")[:2000],
                        json.dumps(factos, ensure_ascii=False)[:2000],
                        json.dumps(fontes, ensure_ascii=False)[:2000],
                        str(draft.get("reviewed_by_model") or "")[:200],
                        legal_doc_id,
                    ),
                )
                conn.commit()
                done += 1

            except Exception as e:
                conn.rollback()
                conn.execute(
                    """
                    UPDATE news_articles
                    SET review_status='FAILED',
                        review_error=?,
                        reviewed_at=datetime('now'),
                        updated_at=datetime('now')
                    WHERE legal_doc_id=?;
                    """.strip(),
                    (str(e)[:900], legal_doc_id),
                )
                conn.commit()
                logger.error(f"Falha na redação, legal_doc_id={legal_doc_id}, erro={e}")

        return done


if __name__ == "__main__":
    import sqlite3

    from vozdipovo_app.db.migrate import ensure_schema
    from vozdipovo_app.modules.base import StageContext
    from vozdipovo_app.settings import get_settings

    settings = get_settings()
    conn = ensure_schema(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        stage = GenerationStage(
            ctx=StageContext(
                conn=conn, app_cfg=settings.app_cfg, editorial=settings.editorial
            ),
            significance_threshold=0.0,
            limit=5,
        )
        print(stage.run())
    finally:
        conn.close()
