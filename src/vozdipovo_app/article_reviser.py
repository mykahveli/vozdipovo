#!filepath: src/vozdipovo_app/article_reviser.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import requests

from vozdipovo_app.editorial.config import get_editorial_config, resolve_model_pool
from vozdipovo_app.llm import (
    ChatMessage,
    ChatRequest,
    LLMProvider,
    LLMRotator,
    ModelSpec,
)
from vozdipovo_app.llm.groq_client import GroqClient
from vozdipovo_app.llm.openrouter_client import OpenRouterClient
from vozdipovo_app.llm.settings import GroqSettings, OpenRouterSettings
from vozdipovo_app.prompts.template import PromptTemplate
from vozdipovo_app.utils.backoff import (
    call_with_exponential_backoff,
    is_retryable_llm_error,
)
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_INPUT_CHARS = int(os.getenv("EDITOR_MAX_INPUT_CHARS", "9000"))
DEFAULT_TIMEOUT = int(os.getenv("EDITOR_TIMEOUT", "45"))

BACKOFF_RETRIES = int(os.getenv("EDITOR_BACKOFF_RETRIES", "5"))
BACKOFF_BASE_DELAY = float(os.getenv("EDITOR_BACKOFF_BASE_DELAY", "2.0"))
BACKOFF_MAX_DELAY = float(os.getenv("EDITOR_BACKOFF_MAX_DELAY", "90.0"))
BACKOFF_JITTER = float(os.getenv("EDITOR_BACKOFF_JITTER", "0.25"))


def _build_rotator() -> LLMRotator:
    editorial = get_editorial_config()
    groq_models = resolve_model_pool(editorial.llm.reviser.groq)

    openrouter_pool = editorial.llm.reviser.openrouter
    openrouter_models = resolve_model_pool(openrouter_pool) if openrouter_pool else []

    groq = GroqClient(GroqSettings(timeout_seconds=DEFAULT_TIMEOUT))

    openrouter: OpenRouterClient | None
    try:
        openrouter = OpenRouterClient(
            OpenRouterSettings(timeout_seconds=DEFAULT_TIMEOUT)
        )
    except Exception:
        openrouter = None

    models: list[ModelSpec] = []
    models.extend([ModelSpec(provider=LLMProvider.GROQ, model=m) for m in groq_models])

    if openrouter is not None and openrouter_models:
        models.extend(
            [
                ModelSpec(provider=LLMProvider.OPENROUTER, model=m)
                for m in openrouter_models
            ]
        )

    return LLMRotator(
        groq=groq,
        openrouter=openrouter,
        models=models,
        default_cooldown_seconds=float(os.getenv("LLM_COOLDOWN_SECONDS", "120")),
    )


@dataclass(frozen=True, slots=True)
class RevisionResult:
    """Normalized revision output from LLM editor."""

    title: str
    text: str
    keywords: str
    categoria_tematica: str
    subcategoria: str
    comentarios_edicao: str

    revision_status: str
    revision_skipped: int
    revision_attempts: int
    revision_model_used: str
    revision_error: str


def _load_editor_prompt_template() -> str:
    possible_paths = [
        Path("configs/prompts/editor.md"),
        Path("prompts/editor.md"),
        Path("configs/prompts/revisao_noticia.md"),
        Path("prompts/revisao_noticia.md"),
        Path(__file__).parent.parent.parent / "configs" / "prompts" / "editor.md",
        Path(__file__).parent.parent.parent / "prompts" / "editor.md",
    ]
    for p in possible_paths:
        if p.exists():
            return p.read_text(encoding="utf-8")

    return (
        "Devolve APENAS JSON com chaves: "
        "titulo_revisto, texto_completo_md_revisto, keywords_revistas, subcategoria, comentarios_edicao, categoria_tematica."
    )


def _sanitize_input(text: str, max_chars: int) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t[:max_chars]


def build_editor_prompt(
    *,
    title: str,
    texto_completo: str,
    keywords: str,
    site_name: str,
    act_type: str,
    categoria_tematica: str,
    subcategoria: str,
    factos_nucleares: Sequence[str],
) -> str:
    template_text = _load_editor_prompt_template()
    template = PromptTemplate(name="editor", text=template_text)
    vars_map = {
        "TITULO": title or "",
        "TEXTO_COMPLETO": _sanitize_input(texto_completo, DEFAULT_MAX_INPUT_CHARS),
        "KEYWORDS": keywords or "",
        "SITE_NAME": site_name or "",
        "ACT_TYPE": act_type or "",
        "CATEGORIA_TEMATICA": categoria_tematica or "",
        "SUBCATEGORIA": subcategoria or "",
        "FACTOS_NUCLEARES": ", ".join(
            [str(x).strip() for x in factos_nucleares if str(x).strip()]
        ),
        "CORPO": _sanitize_input(texto_completo, DEFAULT_MAX_INPUT_CHARS),
    }
    return template.render(vars_map)


def _extract_json_from_response(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    if not s:
        raise ValueError("Resposta vazia do modelo")

    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Resposta não contém JSON detectável")

    json_str = s[start : end + 1]
    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            raise ValueError("JSON não é um objeto")
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON inválido: {e}") from e


def _norm_str(v: Any) -> str:
    return str(v or "").strip()


def _norm_keywords(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join([_norm_str(x) for x in v if _norm_str(x)])
    return _norm_str(v)


def _normalize_revision_payload(
    payload: Dict[str, Any],
    fallback_title: str,
    fallback_text: str,
    fallback_keywords: str,
) -> RevisionResult:
    title = (
        _norm_str(payload.get("titulo_revisto"))
        or _norm_str(payload.get("titulo"))
        or fallback_title
    )
    text = (
        _norm_str(payload.get("texto_completo_md_revisto"))
        or _norm_str(payload.get("corpo_md_revisto"))
        or _norm_str(payload.get("texto_completo_md"))
        or _norm_str(payload.get("corpo_md"))
        or fallback_text
    )
    keywords = (
        _norm_keywords(payload.get("keywords_revistas"))
        or _norm_keywords(payload.get("keywords"))
        or fallback_keywords
    )

    categoria = _norm_str(payload.get("categoria_tematica"))
    subcategoria = _norm_str(payload.get("subcategoria"))
    comentarios = _norm_str(payload.get("comentarios_edicao"))

    return RevisionResult(
        title=title,
        text=text,
        keywords=keywords,
        categoria_tematica=categoria,
        subcategoria=subcategoria,
        comentarios_edicao=comentarios,
        revision_status="revised",
        revision_skipped=0,
        revision_attempts=0,
        revision_model_used="",
        revision_error="",
    )


def revise_article(
    *,
    title: str,
    texto_completo: str,
    keywords: str = "",
    site_name: str = "",
    act_type: str = "",
    categoria_tematica: str = "",
    subcategoria: str = "",
    factos_nucleares: Sequence[str] = (),
    allow_unrevised_fallback: bool = True,
) -> RevisionResult:
    if not texto_completo or not texto_completo.strip():
        return RevisionResult(
            title=title or "",
            text=texto_completo or "",
            keywords=keywords or "",
            categoria_tematica=categoria_tematica or "",
            subcategoria=subcategoria or "",
            comentarios_edicao="Texto vazio; nada para rever.",
            revision_status="unrevised",
            revision_skipped=1,
            revision_attempts=0,
            revision_model_used="",
            revision_error="",
        )

    prompt = build_editor_prompt(
        title=title,
        texto_completo=texto_completo,
        keywords=keywords,
        site_name=site_name,
        act_type=act_type,
        categoria_tematica=categoria_tematica,
        subcategoria=subcategoria,
        factos_nucleares=factos_nucleares,
    )

    rotator = _build_rotator()
    attempts = 0
    last_err: Optional[str] = None

    while True:
        attempts += 1
        try:
            spec = rotator.next_model()
            model_used = f"{spec.provider.value}:{spec.model}"

            req = ChatRequest(
                model=spec.model,
                messages=[ChatMessage(role="user", content=prompt)],
                temperature=0.15,
                max_tokens=1536,
            )

            def _call() -> Dict[str, Any]:
                if spec.provider == LLMProvider.GROQ:
                    resp = rotator.groq.chat(req)
                else:
                    if rotator.openrouter is None:
                        raise RuntimeError("OpenRouter indisponível")
                    resp = rotator.openrouter.chat(req)
                return resp

            resp = call_with_exponential_backoff(
                _call,
                retries=BACKOFF_RETRIES,
                base_delay=BACKOFF_BASE_DELAY,
                max_delay=BACKOFF_MAX_DELAY,
                jitter=BACKOFF_JITTER,
                is_retryable=is_retryable_llm_error,
                logger=logger,
            )

            content = str(resp.get("content") or "").strip()
            payload = _extract_json_from_response(content)
            result = _normalize_revision_payload(
                payload, title, texto_completo, keywords
            )
            return RevisionResult(
                **{
                    **result.__dict__,
                    "revision_attempts": attempts,
                    "revision_model_used": model_used,
                    "revision_error": "",
                }
            )
        except Exception as e:
            last_err = str(e)
            logger.warning(f"Editor falhou tentativa={attempts}, erro={last_err}")
            if attempts >= max(1, BACKOFF_RETRIES) and allow_unrevised_fallback:
                return RevisionResult(
                    title=title,
                    text=texto_completo,
                    keywords=keywords,
                    categoria_tematica=categoria_tematica,
                    subcategoria=subcategoria,
                    comentarios_edicao="Falha no Editor; devolvido texto original.",
                    revision_status="unrevised",
                    revision_skipped=1,
                    revision_attempts=attempts,
                    revision_model_used="",
                    revision_error=last_err or "",
                )
            rotator.cooldown_current()
