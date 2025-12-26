#!src/vozdipovo_app/news_pipeline.py
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from vozdipovo_app.llm.rotator import LLMRotator
from vozdipovo_app.llm.stage_client import get_stage_client_reporter


def _allowed_keys() -> list[str]:
    return [
        "titulo",
        "texto_completo_md",
        "factos_nucleares",
        "fontes_mencionadas",
        "keywords",
        "categoria_tematica",
        "subcategoria",
    ]


def _coerce_str(v: Any) -> str:
    return str(v or "").strip()


def _load_source(conn: sqlite3.Connection, legal_doc_id: int) -> dict[str, str]:
    row = conn.execute(
        """
        SELECT
          site_name,
          act_type,
          title,
          summary,
          content_text,
          url,
          pub_date,
          published_at
        FROM legal_docs
        WHERE id=?
        """,
        (legal_doc_id,),
    ).fetchone()
    if not row:
        return {}

    title = _coerce_str(row["title"])
    summary = _coerce_str(row["summary"])
    body = _coerce_str(row["content_text"])
    url = _coerce_str(row["url"])
    act_type = _coerce_str(row["act_type"])
    site_name = _coerce_str(row["site_name"])
    pub_date = _coerce_str(row["pub_date"] or row["published_at"])

    merged = "\n\n".join([x for x in [title, summary, body] if x]).strip()
    if url:
        merged = f"{merged}\n\nURL: {url}".strip()
    if pub_date:
        merged = f"{merged}\n\nDATA: {pub_date}".strip()

    return {
        "site_name": site_name,
        "act_type": act_type,
        "title": title,
        "corpo": merged,
    }


def generate_one(
    app_cfg: dict[str, Any],
    legal_doc_id: int,
    prompt_path: str,
    conn: sqlite3.Connection,
    rotator: Optional[LLMRotator] = None,
) -> dict[str, Any]:
    """Gera 1 draft via reporter prompt."""
    _ = app_cfg
    _ = rotator

    src = _load_source(conn, legal_doc_id)
    if not src:
        raise RuntimeError(f"Fonte não encontrada, legal_doc_id={legal_doc_id}")

    reporter = get_stage_client_reporter()
    res = reporter.run_json(
        corr_id=f"reporter:{legal_doc_id}",
        template_vars={
            "TITULO": src.get("title", ""),
            "CORPO": src.get("corpo", ""),
            "KEYWORDS": "",
            "SITE_NAME": src.get("site_name", ""),
            "ACT_TYPE": src.get("act_type", ""),
        },
        allowed_keys=_allowed_keys(),
        prompt_path_override=str(prompt_path or "").strip() or None,
        force_models=None,
    )

    if not res.ok or not isinstance(res.parsed_json, dict):
        raise RuntimeError(str(res.error or "Falha no reporter"))

    payload: dict[str, Any] = dict(res.parsed_json or {})
    payload["reviewed_by_model"] = f"{res.provider}:{res.model}".strip(":")
    payload["reporter_payload_json"] = str(res.raw_text or "").strip()
    return payload


if __name__ == "__main__":
    from vozdipovo_app.settings import get_settings

    settings = get_settings()
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    try:
        out = generate_one(
            app_cfg=settings.app_cfg,
            legal_doc_id=1,
            prompt_path=str(
                settings.app_cfg.get("paths", {}).get(
                    "prompt", "configs/prompts/reporter.md"
                )
            ),
            conn=conn,
        )
        print(sorted(out.keys()))
    finally:
        conn.close()
