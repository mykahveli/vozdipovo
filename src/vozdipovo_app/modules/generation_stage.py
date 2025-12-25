#!src/vozdipovo_app/modules/generation_stage.py
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from vozdipovo_app.categories import CategoryContext, resolve_categoria_tematica
from vozdipovo_app.config_editorial import get_editorial_config
from vozdipovo_app.news_pipeline import generate_one
from vozdipovo_app.revision import revise_article
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)

_STOPWORDS = {
    "para",
    "pelo",
    "pela",
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
    if float(significance_threshold or 0.0) > 0.0:
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
            LIMIT ?
            """,
            (float(significance_threshold), int(limit)),
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
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()


def _coerce_keywords(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


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
        "SELECT title, summary, content_text FROM legal_docs WHERE id=?",
        (legal_doc_id,),
    ).fetchone()
    if not row:
        return ""
    parts = [
        str(row["title"] or ""),
        str(row["summary"] or ""),
        str(row["content_text"] or ""),
    ]
    joined = "\n\n".join([p.strip() for p in parts if str(p).strip()])
    return joined.strip()


@dataclass(frozen=True, slots=True)
class GenerationStage:
    """Gera drafts e aplica revisão, persistindo em news_articles."""

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

        prompt_path = str(cfg["paths"].get("prompt", "configs/prompts/reporter.md"))
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
                )
                draft_title = _coerce_text(draft.get("titulo"))
                draft_body = _coerce_text(
                    draft.get("texto_completo_md") or draft.get("corpo_md")
                )
                draft_keywords = _coerce_keywords(draft.get("keywords"))
                draft_categoria = _coerce_text(draft.get("categoria_tematica"))
                draft_subcategoria = _coerce_text(draft.get("subcategoria"))

                if not draft_title or not draft_body:
                    raise RuntimeError("Draft incompleto.")

                rev = revise_article(
                    title=draft_title,
                    raw_article=draft_body,
                    keywords=draft_keywords,
                    site_name=site_name,
                    act_type=act_type,
                    allow_unrevised_fallback=True,
                )

                categoria = resolve_categoria_tematica(
                    CategoryContext(site_name=site_name, act_type=act_type),
                    model_category=(rev.categoria_tematica or "").strip(),
                    draft_category=draft_categoria,
                    fallback="Geral",
                )
                subcategoria = (rev.subcategoria or "").strip() or draft_subcategoria
                titulo_final = (rev.title or "").strip() or draft_title
                corpo_final = (rev.text or "").strip() or draft_body
                keywords_final = (rev.keywords or "").strip() or draft_keywords

                common, ratio = _overlap_stats(source, f"{titulo_final}\n{corpo_final}")
                if common < min_overlap_tokens or ratio < min_overlap_ratio:
                    raise RuntimeError(
                        f"Baixa fidelidade, common={common}, ratio={ratio:.4f}"
                    )

                status = "SUCCESS" if rev.revision_status == "revised" else "FAILED"
                review_error = (rev.revision_error or "").strip()[:900]

                conn.execute(
                    """
                    UPDATE news_articles
                    SET titulo=?,
                        corpo_md=?,
                        keywords=?,
                        categoria_tematica=?,
                        subcategoria=?,
                        editor_comments=?,
                        reviewed_by_model=?,
                        review_error=?,
                        review_status=?,
                        reviewed_at=datetime('now')
                    WHERE legal_doc_id=?
                    """,
                    (
                        titulo_final,
                        corpo_final,
                        keywords_final,
                        categoria,
                        subcategoria,
                        (rev.comentarios_edicao or "")[:900],
                        (rev.revision_model_used or "")[:200],
                        review_error,
                        status,
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
                        reviewed_at=datetime('now')
                    WHERE legal_doc_id=?
                    """,
                    (str(e)[:900], legal_doc_id),
                )
                conn.commit()
                logger.error(f"Falha na redação, legal_doc_id={legal_doc_id}, erro={e}")

        return done


if __name__ == "__main__":
    import sqlite3

    from vozdipovo_app.modules.base import StageContext
    from vozdipovo_app.settings import get_settings

    settings = get_settings()
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        stage = GenerationStage(
            ctx=StageContext(
                conn=conn, app_cfg=settings.app_cfg, editorial=settings.editorial
            ),
            significance_threshold=0.0,
            limit=5,
        )
        processed = stage.run()
        conn.commit()
        print(processed)
    finally:
        conn.close()
