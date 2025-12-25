#!src/vozdipovo_app/db/schema.py
from __future__ import annotations

SCHEMA = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS legal_docs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_name TEXT NOT NULL,
  source_type TEXT NOT NULL,

  url TEXT NOT NULL,
  url_hash TEXT,

  act_type TEXT,
  title TEXT,

  pub_date TEXT,
  published_at TEXT,

  summary TEXT,
  content_text TEXT,
  raw_html TEXT,
  raw_payload_json TEXT,

  fetched_at TEXT,

  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_legal_docs_url_hash
ON legal_docs(url_hash);

CREATE UNIQUE INDEX IF NOT EXISTS idx_legal_docs_url
ON legal_docs(url);

CREATE TABLE IF NOT EXISTS news_articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  legal_doc_id INTEGER NOT NULL,

  categoria_tematica TEXT,
  subcategoria TEXT,

  titulo TEXT,
  corpo_md TEXT,

  keywords TEXT,
  keywords_json TEXT,

  reporter_payload_json TEXT,
  reporter_factos_json TEXT,
  reporter_fontes_json TEXT,
  editor_checklist_json TEXT,

  score_scale INTEGER,
  score_impact INTEGER,
  score_novelty INTEGER,
  score_potential INTEGER,
  score_legacy INTEGER,
  score_credibility INTEGER,
  score_positivity INTEGER,
  score_cv_relevance INTEGER,

  final_score REAL,
  score_editorial REAL,
  judge_justification TEXT,
  editor_comments TEXT,

  decision TEXT,

  review_status TEXT,
  review_error TEXT,
  review_attempts INTEGER DEFAULT 0,
  review_next_retry_at TEXT,
  review_error_kind TEXT,
  review_http_status INTEGER,
  reviewed_at TEXT,
  reviewed_by_model TEXT,

  publishing_status TEXT,
  published_at TEXT,
  wp_post_id INTEGER,
  wp_url TEXT,
  wp_error TEXT,

  highlight_status TEXT,
  highlight_reason TEXT,

  audio_status TEXT,
  audio_path TEXT,
  audio_error TEXT,

  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),

  FOREIGN KEY (legal_doc_id) REFERENCES legal_docs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_news_articles_legal_doc_id
ON news_articles(legal_doc_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_legal_doc_id_uq
ON news_articles(legal_doc_id);

CREATE INDEX IF NOT EXISTS idx_news_articles_review_status
ON news_articles(review_status);

CREATE INDEX IF NOT EXISTS idx_news_articles_decision
ON news_articles(decision);
"""
