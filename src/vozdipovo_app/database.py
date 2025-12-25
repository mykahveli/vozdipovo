import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA = """CREATE TABLE IF NOT EXISTS processed_texts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL,
    file_mtime REAL NOT NULL,
    file_hash TEXT NOT NULL,
    content_text TEXT NOT NULL,
    prompt_used TEXT NOT NULL,
    response_text TEXT,
    status TEXT NOT NULL,
    error TEXT,
    model TEXT,
    api_version TEXT,
    temperature REAL,
    top_p REAL,
    max_tokens INTEGER,
    usage_prompt_tokens INTEGER,
    usage_completion_tokens INTEGER,
    usage_total_tokens INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_processed_filehash ON processed_texts(file_hash);
"""

def ensure_db(db_path: str):
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)  # <— cria diretório
    conn = sqlite3.connect(str(p))               # <— usa str(p)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    return conn

def sha256_text(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def already_processed(conn, file_hash: str) -> bool:
    cur = conn.execute("SELECT 1 FROM processed_texts WHERE file_hash = ? LIMIT 1", (file_hash,))
    return cur.fetchone() is not None

def insert_row(conn, row: dict) -> int:
    keys = ", ".join(row.keys())
    qmarks = ", ".join(["?"] * len(row))
    cur = conn.execute(f"INSERT INTO processed_texts ({keys}) VALUES ({qmarks})", tuple(row.values()))
    conn.commit()
    return cur.lastrowid

def update_row_response(conn, row_id: int, response_text: Optional[str], status: str, usage: Optional[dict] = None, error: Optional[str] = None):
    fields = ["response_text = ?", "status = ?", "error = ?"]
    vals = [response_text, status, error]
    if usage:
        fields.extend(["usage_prompt_tokens = ?","usage_completion_tokens = ?","usage_total_tokens = ?"])
        vals.extend([usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens")])
    vals.append(row_id)
    sql = f"UPDATE processed_texts SET {', '.join(fields)} WHERE id = ?"
    conn.execute(sql, vals)
    conn.commit()
