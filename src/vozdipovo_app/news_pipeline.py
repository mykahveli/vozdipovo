#!filepath: src/vozdipovo_app/news_pipeline.py
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from vozdipovo_app.editorial.config import get_editorial_config
from vozdipovo_app.llm.models import ChatMessage, ChatRequest
from vozdipovo_app.llm.rotator import LLMRotator
from vozdipovo_app.utils.backoff import (
    call_with_exponential_backoff,
    is_retryable_llm_error,
)
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TokenBudget:
    model_name: str
    max_tokens: int

    def estimate_tokens(self, text: str) -> int:
        try:
            import tiktoken

            enc = tiktoken.encoding_for_model(self.model_name)
            return len(enc.encode(text))
        except Exception:
            return max(1, len(text) // 4)

    def truncate_to_budget(self, text: str) -> str:
        if not text:
            return ""
        est = self.estimate_tokens(text)
        if est <= self.max_tokens:
            return text
        ratio = float(self.max_tokens) / float(max(1, est))
        keep = max(1, int(len(text) * ratio))
        return text[:keep]


def _strict_json_dict(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Resposta não é um objeto JSON.")
    return data


def generate_one(
    cfg: Dict[str, Any],
    legal_doc_id: int,
    prompt_path: str,
    *,
    conn: sqlite3.Connection,
    rotator: LLMRotator,
    model_name_for_budget: str = "gpt-4o-mini",
) -> Dict[str, Any]:
    prompt_file = Path(prompt_path)
    template = prompt_file.read_text(encoding="utf-8")

    row = conn.execute(
        "SELECT title, summary, text, site_name, act_type FROM legal_docs WHERE id=?",
        (legal_doc_id,),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Fonte não encontrada, legal_doc_id={legal_doc_id}")

    titulo = str(row["title"] or "")
    corpo = "\n\n".join(
        [str(row["summary"] or "").strip(), str(row["text"] or "").strip()]
    ).strip()
    site_name = str(row["site_name"] or "")
    act_type = str(row["act_type"] or "")

    budget = TokenBudget(model_name=model_name_for_budget, max_tokens=3000)
    corpo = budget.truncate_to_budget(corpo)

    prompt = (
        template.replace("{{TITULO}}", titulo)
        .replace("{{CORPO}}", corpo)
        .replace("{{SITE_NAME}}", site_name)
        .replace("{{ACT_TYPE}}", act_type)
    )

    def _call_once() -> str:
        req = ChatRequest(
            model="",
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        resp = rotator.chat(req)
        packed = {"_model": f"{resp.provider}/{resp.model}", "_content": resp.content}
        return json.dumps(packed, ensure_ascii=False)

    packed = call_with_exponential_backoff(
        _call_once,
        max_retries=6,
        base_delay=1.0,
        max_delay=40.0,
        is_retryable=is_retryable_llm_error,
        logger=logger,
    )
    wrapper = _strict_json_dict(packed)
    content = str(wrapper.get("_content") or "")
    data = _strict_json_dict(content)
    data["writer_model_used"] = str(wrapper.get("_model") or "")
    return data
