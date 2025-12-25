#!src/vozdipovo_app/modules/generation_stage.py
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from vozdipovo_app.article_reviser import revise_article
from vozdipovo_app.category_rules import CategoryContext, resolve_categoria_tematica
from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.modules.base import Stage, StageContext
from vozdipovo_app.news_pipeline import generate_one
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)

_STOPWORDS = {
    "para",
    "pela",
    "pelo",
    "entre",
    "sobre",
    "desde",
    "como",
    "onde",
    "quando",
    "porque",
    "qual",
    "quais",
    "num",
    "numa",
    "nos",
    "nas",
    "uma",
    "umas",
    "uns",
    "que",
    "com",
    "sem",
    "por",
    "dos",
    "das",
    "aos",
    "às",
    "este",
    "esta",
    "isso",
    "isto",
    "será",
    "são",
    "foi",
    "têm",
    "tem",
    "mais",
    "menos",
    "muito",
    "muita",
    "também",
}

_LEGAL_DOCS_CONTENT_COL: str | None = None


def _candidates(
    conn: sqlite3.Connection, significance_threshold: float, limit: int
) -> Sequence[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          a.legal_doc_id,
          d.site_name,
          d.act_type
        FROM news_articles a
        JOIN legal_docs d ON d.id = a.legal_doc_id
        WHERE a.final_score >= ?
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
        (significance_threshold, limit),
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


def _legal_docs_columns(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(legal_docs)").fetchall()
    return {str(r[1]) for r in rows if r and len(r) > 1}


def _resolve_legal_docs_content_column(conn: sqlite3.Connection) -> str | None:
    global _LEGAL_DOCS_CONTENT_COL
    if _LEGAL_DOCS_CONTENT_COL is not None:
        return _LEGAL_DOCS_CONTENT_COL

    cols = _legal_docs_columns(conn)
    for candidate in ("content_text", "text", "raw_payload_json", "raw_html"):
        if candidate in cols:
            _LEGAL_DOCS_CONTENT_COL = candidate
            return _LEGAL_DOCS_CONTENT_COL

    _LEGAL_DOCS_CONTENT_COL = None
    return None


def _source_text(conn: sqlite3.Connection, legal_doc_id: int) -> str:
    content_col = _resolve_legal_docs_content_column(conn)
    if not content_col:
        row = conn.execute(
            "SELECT title, summary FROM legal_docs WHERE id=?",
            (legal_doc_id,),
        ).fetchone()
        if not row:
            return ""
        parts = [str(row["title"] or ""), str(row["summary"] or "")]
        joined = "\n\n".join([p.strip() for p in parts if str(p).strip()])
        return joined.strip()

    row = conn.execute(
        f"SELECT title, summary, {content_col} AS content FROM legal_docs WHERE id=?",
        (legal_doc_id,),
    ).fetchone()
    if not row:
        return ""
    parts = [
        str(row["title"] or ""),
        str(row["summary"] or ""),
        str(row["content"] or ""),
    ]
    joined = "\n\n".join([p.strip() for p in parts if str(p).strip()])
    return joined.strip()


@dataclass(frozen=True, slots=True)
class GenerationStage(Stage):
    ctx: StageContext
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
                    cfg, legal_doc_id, prompt_path, conn=conn, rotator=self.ctx.rotator
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
    import sqlite3 as _sqlite3

    from vozdipovo_app.modules.base import build_stage_context as _build_stage_context
    from vozdipovo_app.settings import get_settings as _get_settings

    settings = _get_settings()
    conn = _sqlite3.connect(str(settings.db_path))
    conn.row_factory = _sqlite3.Row
    ctx = _build_stage_context(conn)
    stage = GenerationStage(ctx=ctx, significance_threshold=0.0, limit=5)
    print(stage.run())
