#!filepath: src/vozdipovo_app/analytics/scoring_stats.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True, slots=True)
class ScoreStats:
    count: int
    avg: float
    median: float
    p75: float
    p90: float
    min: float
    max: float


def _percentile(conn: sqlite3.Connection, column: str, p: float) -> float:
    row = conn.execute(
        f"""
        SELECT {column}
        FROM news_articles
        WHERE review_status='SUCCESS'
        ORDER BY {column}
        LIMIT 1
        OFFSET (
          SELECT CAST(COUNT(*) * ? AS INT)
          FROM news_articles
          WHERE review_status='SUCCESS'
        )
        """,
        (p,),
    ).fetchone()
    return float(row[0]) if row else 0.0


def compute_stats(conn: sqlite3.Connection, column: str) -> ScoreStats:
    base = conn.execute(
        f"""
        SELECT
          COUNT(*)  AS cnt,
          AVG({column}),
          MIN({column}),
          MAX({column})
        FROM news_articles
        WHERE review_status='SUCCESS'
        """
    ).fetchone()

    cnt = int(base[0] or 0)
    avg = float(base[1] or 0.0)
    min_v = float(base[2] or 0.0)
    max_v = float(base[3] or 0.0)

    median = _percentile(conn, column, 0.5)
    p75 = _percentile(conn, column, 0.75)
    p90 = _percentile(conn, column, 0.90)

    return ScoreStats(
        count=cnt,
        avg=round(avg, 3),
        median=round(median, 3),
        p75=round(p75, 3),
        p90=round(p90, 3),
        min=round(min_v, 3),
        max=round(max_v, 3),
    )
