#!src/vozdipovo_app/article_reviser.py
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from pydantic import ValidationError

from vozdipovo_app.llm.groq_client import GroqClient, GroqConfig
from vozdipovo_app.llm.models import ChatRequest, LLMProvider, Message
from vozdipovo_app.llm.rotator import LLMRotator, ModelSpec
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RevisionResult:
    """Resultado da revisão.

    Attributes:
        ok: Indica sucesso.
        revised_text: Texto revisto.
        model_used: Modelo usado.
        raw_json: JSON bruto quando aplicável.
        error: Erro em caso de falha.
    """

    ok: bool
    revised_text: Optional[str]
    model_used: Optional[str]
    raw_json: Optional[Dict[str, Any]]
    error: Optional[str]


def _build_rotator(models: Sequence[str], timeout_seconds: float) -> LLMRotator:
    """Constrói um rotator para revisão.

    Args:
        models: Lista de modelos.
        timeout_seconds: Timeout do provider.

    Returns:
        Instância de LLMRotator.

    Raises:
        ValidationError: Quando GROQ_API_KEY não está disponível.
    """
    cfg = GroqConfig.from_env().model_copy(
        update={"timeout_seconds": int(timeout_seconds)}
    )
    client = GroqClient(cfg)
    specs = [ModelSpec(provider=LLMProvider.GROQ, model=m) for m in models]
    return LLMRotator(
        groq=client,
        openrouter=None,
        models=specs,
    )


def revise_article(
    text: str,
    models: Sequence[str],
    timeout_seconds: float = 60.0,
    temperature: float = 0.2,
) -> RevisionResult:
    """Revisa um artigo com LLM e devolve resultado estruturado.

    Args:
        text: Texto do artigo.
        models: Lista de modelos.
        timeout_seconds: Timeout do provider.
        temperature: Temperatura.

    Returns:
        RevisionResult: Resultado da revisão.
    """
    if not text or not str(text).strip():
        return RevisionResult(
            ok=False,
            revised_text=None,
            model_used=None,
            raw_json=None,
            error="Texto vazio",
        )

    try:
        rotator = _build_rotator(models=models, timeout_seconds=timeout_seconds)
    except ValidationError as e:
        return RevisionResult(
            ok=False,
            revised_text=None,
            model_used=None,
            raw_json=None,
            error=f"Config inválida: {e}",
        )
    except Exception as e:
        return RevisionResult(
            ok=False,
            revised_text=None,
            model_used=None,
            raw_json=None,
            error=f"Falha ao construir rotator: {e}",
        )

    req = ChatRequest(
        model=None,
        messages=[
            Message(
                role="system",
                content="Reescreve e melhora o texto, mantém factos, melhora clareza.",
            ),
            Message(role="user", content=text),
        ],
        temperature=temperature,
        max_tokens=None,
    )

    try:
        resp = rotator.chat(req)
        revised = (resp.content or "").strip()
        if not revised:
            return RevisionResult(
                ok=False,
                revised_text=None,
                model_used=resp.model,
                raw_json=resp.raw,
                error="Resposta vazia",
            )
        return RevisionResult(
            ok=True,
            revised_text=revised,
            model_used=resp.model,
            raw_json=resp.raw,
            error=None,
        )
    except Exception as e:
        return RevisionResult(
            ok=False,
            revised_text=None,
            model_used=None,
            raw_json=None,
            error=f"Falha na revisão: {e}",
        )


if __name__ == "__main__":
    demo = revise_article(
        text="Texto de teste para revisão.",
        models=["llama-3.1-70b-versatile"],
        timeout_seconds=30.0,
        temperature=0.2,
    )
    logger.info(json.dumps(demo.__dict__, ensure_ascii=False))
