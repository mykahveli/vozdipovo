#!filepath: scripts/stats_scores_global.py
from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True, slots=True)
class ScoreStats:
    count: int
    avg: float
    median: float
    p75: float
    p90: float
    min: float
    max: float


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _col_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return any(str(r["name"]).lower() == column.lower() for r in rows)


def _pick_score_column(
    conn: sqlite3.Connection, candidates: List[str]
) -> Optional[str]:
    for c in candidates:
        if _col_exists(conn, "news_articles", c):
            return c
    return None


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if p <= 0:
        return float(sorted_vals[0])
    if p >= 1:
        return float(sorted_vals[-1])
    idx = (len(sorted_vals) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return float(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac)


def _stats(vals: List[float]) -> ScoreStats:
    vals = [float(v) for v in vals if v is not None]
    vals.sort()
    if not vals:
        return ScoreStats(
            count=0, avg=0.0, median=0.0, p75=0.0, p90=0.0, min=0.0, max=0.0
        )
    count = len(vals)
    avg = sum(vals) / count
    median = _percentile(vals, 0.5)
    p75 = _percentile(vals, 0.75)
    p90 = _percentile(vals, 0.9)
    return ScoreStats(
        count=count,
        avg=round(avg, 3),
        median=round(median, 2),
        p75=round(p75, 2),
        p90=round(p90, 2),
        min=round(vals[0], 2),
        max=round(vals[-1], 2),
    )


def _fetch_vals(
    conn: sqlite3.Connection,
    col: str,
    where: str,
    params: Tuple[Any, ...],
) -> List[float]:
    q = f"SELECT {col} AS v FROM news_articles na JOIN legal_docs ld ON ld.id=na.legal_doc_id WHERE {where} AND {col} IS NOT NULL"
    return [
        float(r["v"]) for r in conn.execute(q, params).fetchall() if r["v"] is not None
    ]


def _group_stats(
    conn: sqlite3.Connection,
    col: str,
    group_col: str,
    where: str,
) -> List[Tuple[str, ScoreStats]]:
    q = f"""
SELECT {group_col} AS g, {col} AS v
FROM news_articles na
JOIN legal_docs ld ON ld.id = na.legal_doc_id
WHERE {where}
  AND {col} IS NOT NULL
"""
    buckets: Dict[str, List[float]] = {}
    for r in conn.execute(q):
        g = str(r["g"] if r["g"] is not None else "NULL")
        buckets.setdefault(g, []).append(float(r["v"]))
    out = [(k, _stats(v)) for k, v in buckets.items()]
    out.sort(key=lambda x: x[1].count, reverse=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="configs/vozdipovo.db")
    parser.add_argument(
        "--scope", choices=("all", "judged", "success", "published"), default="all"
    )
    args = parser.parse_args()

    conn = _connect(args.db)
    try:
        final_col = _pick_score_column(
            conn, ["final_score", "final_significance_score"]
        )
        editorial_col = _pick_score_column(conn, ["score_editorial"])
        cv_col = _pick_score_column(conn, ["score_cv_relevance", "cv_relevance_score"])
        impact_col = _pick_score_column(conn, ["score_impact", "impact_score"])
        novelty_col = _pick_score_column(conn, ["score_novelty", "novelty_score"])
        potential_col = _pick_score_column(conn, ["score_potential", "potential_score"])
        legacy_col = _pick_score_column(conn, ["score_legacy", "legacy_score"])
        cred_col = _pick_score_column(conn, ["score_credibility", "credibility_score"])

        where = "1=1"
        if args.scope == "judged":
            where = "na.review_status IN ('JUDGED','SUCCESS')"
        elif args.scope == "success":
            where = "na.review_status='SUCCESS'"
        elif args.scope == "published":
            where = "na.publishing_status='SUCCESS'"

        cols = [
            ("final_score", final_col),
            ("score_editorial", editorial_col),
            ("score_cv_relevance", cv_col),
            ("score_impact", impact_col),
            ("score_novelty", novelty_col),
            ("score_potential", potential_col),
            ("score_legacy", legacy_col),
            ("score_credibility", cred_col),
        ]

        print(f"📌 Scope: {args.scope}  |  WHERE: {where}\n")

        for label, col in cols:
            if not col:
                continue
            vals = _fetch_vals(conn, col, where, ())
            st = _stats(vals)
            print(f"📊 {label}")
            print(st)
            print()

        if editorial_col:
            print("📎 Por fonte (site_name) — score_editorial (top por volume)")
            for g, st in _group_stats(conn, editorial_col, "ld.site_name", where):
                print(f"{g} | {st}")
            print()

        if editorial_col:
            print("📎 Por categoria_tematica — score_editorial (top por volume)")
            gcol = (
                "na.categoria_tematica"
                if _col_exists(conn, "news_articles", "categoria_tematica")
                else "NULL"
            )
            for g, st in _group_stats(conn, editorial_col, gcol, where):
                print(f"{g} | {st}")
            print()

        if final_col:
            print("📎 Por modelo do juiz — final_score (top por volume)")
            mcol = (
                "na.judge_model_used"
                if _col_exists(conn, "news_articles", "judge_model_used")
                else "NULL"
            )
            for g, st in _group_stats(conn, final_col, mcol, where):
                print(f"{g} | {st}")
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
