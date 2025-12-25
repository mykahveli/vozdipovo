#!filepath: scripts/stats_scores.py
#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
from pprint import pprint

from vozdipovo_app.analytics.scoring_stats import compute_stats

DB = "configs/vozdipovo.db"
COLUMNS = [
    "final_score",
    "score_editorial",
    "score_impact",
    "score_novelty",
    "score_potential",
    "score_legacy",
    "score_credibility",
    "score_cv_relevance",
]

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

for col in COLUMNS:
    stats = compute_stats(conn, col)
    print(f"\n📊 {col}")
    pprint(stats)

conn.close()
