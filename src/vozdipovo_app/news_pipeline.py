#!src/vozdipovo_app/news_pipeline.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

from vozdipovo_app.llm.rotator import LLMRotator
from vozdipovo_app.llm.stage_client import get_stage_client_reporter
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReporterDraft:
    titulo: str
    texto_completo_md: str
    factos_nucleares: list[str]
    fontes_mencionadas: list[str]
    keywords: list[str]
    categoria_tematica: str
    subcategoria: str
    reporter_payload_json: str
    reviewed_by_model: str


def _coerce_list_str(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    return [s] if s else []


def _coerce_str(v: Any) -> str:
    return str(v or "").strip()


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
    _ = rotator

    src = _load_source(conn, legal_doc_id)
    if not src:
        raise RuntimeError(f"Fonte não encontrada, legal_doc_id={legal_doc_id}")

    reporter = get_stage_client_reporter()
    title = src.get("title", "")
    corpo = src.get("corpo", "")
    site_name = src.get("site_name", "")
    act_type = src.get("act_type", "")

    res = reporter.run_json(
        prompt_path=prompt_path,
        template_vars={
            "TITULO": title,
            "CORPO": corpo,
            "KEYWORDS": "",
            "SITE_NAME": site_name,
            "ACT_TYPE": act_type,
        },
        allowed_keys=_allowed_keys(),
    )

    payload = res.data if isinstance(res.data, dict) else {}
    payload["reviewed_by_model"] = f"{res.provider_used}:{res.model_used}".strip(":")
    payload["reporter_payload_json"] = res.raw_text or ""
    return payload


if __name__ == "__main__":
    import sqlite3

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
        print(out.keys())
    finally:
        conn.close()
