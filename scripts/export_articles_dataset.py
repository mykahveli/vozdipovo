#!filepath: scripts/export_articles_dataset.py
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True, slots=True)
class ExportRow:
    legal_doc_id: int
    site_name: Optional[str]
    url: Optional[str]
    act_type: Optional[str]

    titulo: Optional[str]
    categoria_tematica: Optional[str]
    subcategoria: Optional[str]
    tags: Optional[str]

    review_status: Optional[str]
    reviewed_at: Optional[str]
    review_error: Optional[str]
    reviewed_by_model: Optional[str]

    publishing_status: Optional[str]
    wp_post_id: Optional[int]
    published_at: Optional[str]
    publishing_error: Optional[str]

    highlight_type: Optional[str]

    final_score: Optional[float]
    score_editorial: Optional[float]

    score_scale: Optional[int]
    score_impact: Optional[int]
    score_novelty: Optional[int]
    score_potential: Optional[int]
    score_legacy: Optional[int]
    score_credibility: Optional[int]
    score_positivity: Optional[int]
    score_cv_relevance: Optional[int]

    judge_model_used: Optional[str]

    created_at: Optional[str]
    updated_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "legal_doc_id": self.legal_doc_id,
            "site_name": self.site_name,
            "url": self.url,
            "act_type": self.act_type,
            "titulo": self.titulo,
            "categoria_tematica": self.categoria_tematica,
            "subcategoria": self.subcategoria,
            "tags": self.tags,
            "review_status": self.review_status,
            "reviewed_at": self.reviewed_at,
            "review_error": self.review_error,
            "reviewed_by_model": self.reviewed_by_model,
            "publishing_status": self.publishing_status,
            "wp_post_id": self.wp_post_id,
            "published_at": self.published_at,
            "publishing_error": self.publishing_error,
            "highlight_type": self.highlight_type,
            "final_score": self.final_score,
            "score_editorial": self.score_editorial,
            "score_scale": self.score_scale,
            "score_impact": self.score_impact,
            "score_novelty": self.score_novelty,
            "score_potential": self.score_potential,
            "score_legacy": self.score_legacy,
            "score_credibility": self.score_credibility,
            "score_positivity": self.score_positivity,
            "score_cv_relevance": self.score_cv_relevance,
            "judge_model_used": self.judge_model_used,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _table_has_details(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN stage='judging' THEN 1 ELSE 0 END) AS total,
          SUM(CASE WHEN stage='judging' AND details_json IS NOT NULL AND details_json != '' THEN 1 ELSE 0 END) AS with_details
        FROM pipeline_log
        """
    ).fetchone()
    if not row:
        return False
    return int(row["with_details"] or 0) > 0


def _iter_rows(conn: sqlite3.Connection) -> Iterable[ExportRow]:
    has_judge_details = _table_has_details(conn)

    if has_judge_details:
        sql = """
        WITH last_judge AS (
          SELECT
            pl.legal_doc_id,
            pl.details_json,
            pl.timestamp,
            ROW_NUMBER() OVER (PARTITION BY pl.legal_doc_id ORDER BY pl.timestamp DESC, pl.log_id DESC) AS rn
          FROM pipeline_log pl
          WHERE pl.stage = 'judging'
        )
        SELECT
          na.legal_doc_id,
          ld.site_name,
          ld.url,
          ld.act_type,
          na.titulo,
          na.categoria_tematica,
          na.subcategoria,
          na.tags,
          na.review_status,
          na.reviewed_at,
          na.review_error,
          na.reviewed_by_model,
          na.publishing_status,
          na.wp_post_id,
          na.published_at,
          na.publishing_error,
          na.highlight_type,
          na.final_score,
          na.score_editorial,
          na.score_scale,
          na.score_impact,
          na.score_novelty,
          na.score_potential,
          na.score_legacy,
          na.score_credibility,
          na.score_positivity,
          na.score_cv_relevance,
          json_extract(lj.details_json, '$.judge_model_used') AS judge_model_used,
          na.created_at,
          na.updated_at
        FROM news_articles na
        JOIN legal_docs ld ON ld.id = na.legal_doc_id
        LEFT JOIN last_judge lj ON lj.legal_doc_id = na.legal_doc_id AND lj.rn = 1
        ORDER BY na.legal_doc_id DESC
        """
    else:
        sql = """
        SELECT
          na.legal_doc_id,
          ld.site_name,
          ld.url,
          ld.act_type,
          na.titulo,
          na.categoria_tematica,
          na.subcategoria,
          na.tags,
          na.review_status,
          na.reviewed_at,
          na.review_error,
          na.reviewed_by_model,
          na.publishing_status,
          na.wp_post_id,
          na.published_at,
          na.publishing_error,
          na.highlight_type,
          na.final_score,
          na.score_editorial,
          na.score_scale,
          na.score_impact,
          na.score_novelty,
          na.score_potential,
          na.score_legacy,
          na.score_credibility,
          na.score_positivity,
          na.score_cv_relevance,
          NULL AS judge_model_used,
          na.created_at,
          na.updated_at
        FROM news_articles na
        JOIN legal_docs ld ON ld.id = na.legal_doc_id
        ORDER BY na.legal_doc_id DESC
        """

    for r in conn.execute(sql):
        yield ExportRow(
            legal_doc_id=int(r["legal_doc_id"]),
            site_name=r["site_name"],
            url=r["url"],
            act_type=r["act_type"],
            titulo=r["titulo"],
            categoria_tematica=r["categoria_tematica"],
            subcategoria=r["subcategoria"],
            tags=r["tags"],
            review_status=r["review_status"],
            reviewed_at=r["reviewed_at"],
            review_error=r["review_error"],
            reviewed_by_model=r["reviewed_by_model"],
            publishing_status=r["publishing_status"],
            wp_post_id=r["wp_post_id"],
            published_at=r["published_at"],
            publishing_error=r["publishing_error"],
            highlight_type=r["highlight_type"],
            final_score=_safe_float(r["final_score"]),
            score_editorial=_safe_float(r["score_editorial"]),
            score_scale=_safe_int(r["score_scale"]),
            score_impact=_safe_int(r["score_impact"]),
            score_novelty=_safe_int(r["score_novelty"]),
            score_potential=_safe_int(r["score_potential"]),
            score_legacy=_safe_int(r["score_legacy"]),
            score_credibility=_safe_int(r["score_credibility"]),
            score_positivity=_safe_int(r["score_positivity"]),
            score_cv_relevance=_safe_int(r["score_cv_relevance"]),
            judge_model_used=r["judge_model_used"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )


def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _write_csv(path: Path, rows: Iterable[ExportRow]) -> None:
    rows_list = list(rows)
    if not rows_list:
        raise RuntimeError("Não há linhas para exportar.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_list[0].to_dict().keys()))
        w.writeheader()
        for row in rows_list:
            w.writerow(row.to_dict())


def _write_jsonl(path: Path, rows: Iterable[ExportRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="configs/vozdipovo.db")
    parser.add_argument("--outdir", default="data/exports")
    parser.add_argument("--format", choices=("csv", "jsonl", "both"), default="both")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    conn = _connect(args.db)
    try:
        rows = list(_iter_rows(conn))
    finally:
        conn.close()

    if args.format in ("csv", "both"):
        _write_csv(outdir / "articles.csv", rows)
    if args.format in ("jsonl", "both"):
        _write_jsonl(outdir / "articles.jsonl", rows)

    print(f"✅ Export concluído: {outdir}/articles.csv e/ou {outdir}/articles.jsonl")


if __name__ == "__main__":
    main()
