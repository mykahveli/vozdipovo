#!src/vozdipovo_app/llm/stage_client.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from vozdipovo_app.editorial.config import get_editorial_config, resolve_model_pool
from vozdipovo_app.editorial.models import ModelPool
from vozdipovo_app.llm.router import LLMRouter


def _apply_template(text: str, template_vars: dict[str, str]) -> str:
    out = text
    for k, v in template_vars.items():
        out = out.replace("{{" + k + "}}", str(v or ""))
    return out


def _filter_allowed_keys(
    obj: dict[str, Any] | None, allowed_keys: Iterable[str] | None
) -> dict[str, Any] | None:
    if obj is None:
        return None
    if not allowed_keys:
        return obj
    allow = {str(k) for k in allowed_keys}
    return {k: v for k, v in obj.items() if k in allow}


def _resolve_prompts_dir() -> str:
    env = os.getenv("VOZDIPOPO_PROMPTS_DIR") or ""
    if env.strip():
        return env.strip()
    return "configs/prompts"


@dataclass(frozen=True, slots=True)
class StageRunResult:
    """Resultado padronizado de uma execução de stage LLM."""

    ok: bool
    provider: str
    model: str
    raw_text: str
    parsed_json: dict[str, Any] | None
    error: str


class LlmStageClient:
    """Cliente simples para executar prompts por stage com rotação de modelos."""

    def __init__(
        self,
        *,
        router: LLMRouter,
        prompt_path_default: str,
    ) -> None:
        self._router = router
        self._prompt_path_default = str(prompt_path_default)

    def run_json(
        self,
        *,
        template_vars: dict[str, str],
        allowed_keys: Iterable[str] | None = None,
        prompt_path: str | None = None,
        prompt_path_override: str | None = None,
        corr_id: str | None = None,
        force_models: list[str] | None = None,
    ) -> StageRunResult:
        """Executa um prompt e tenta obter JSON.

        Args:
            template_vars: Variáveis para preencher no prompt.
            allowed_keys: Se indicado, filtra apenas estas chaves.
            prompt_path: Override do caminho do prompt (preferido).
            prompt_path_override: Alias legado para override do caminho do prompt.
            corr_id: Correlation id (para logs/trace).
            force_models: Lista de modelos a forçar.

        Returns:
            StageRunResult: Resultado com JSON parseado quando possível.
        """
        chosen_path = str(
            prompt_path_override or prompt_path or self._prompt_path_default
        )
        p = Path(chosen_path)
        prompt_raw = p.read_text(encoding="utf-8")
        prompt = _apply_template(prompt_raw, template_vars)

        res = self._router.run_json(
            corr_id=str(corr_id or ""),
            prompt=prompt,
            force_models=force_models,
        )

        return StageRunResult(
            ok=res.ok,
            provider=res.provider,
            model=res.model,
            raw_text=res.text,
            parsed_json=_filter_allowed_keys(res.parsed_json, allowed_keys),
            error=res.error,
        )


def _pool_or_fallback(
    primary: ModelPool | None, fallback: ModelPool | None
) -> ModelPool:
    if primary is not None:
        return primary
    if fallback is not None:
        return fallback
    return ModelPool(primary=[], fallback=[])


def _router_from_pool(pool: ModelPool | None) -> LLMRouter:
    models = resolve_model_pool(pool or ModelPool(primary=[], fallback=[]))
    return LLMRouter.from_stage_models(models=models)


def get_stage_client_reporter() -> LlmStageClient:
    cfg = get_editorial_config()
    prompts_dir = _resolve_prompts_dir()
    prompt = str(Path(prompts_dir) / "reporter.md")
    pool = _pool_or_fallback(cfg.llm.reporter, cfg.llm.reviser)
    return LlmStageClient(router=_router_from_pool(pool), prompt_path_default=prompt)


def get_stage_client_director() -> LlmStageClient:
    cfg = get_editorial_config()
    prompts_dir = _resolve_prompts_dir()
    prompt = str(Path(prompts_dir) / "diretor.md")
    pool = _pool_or_fallback(cfg.llm.judge, cfg.llm.reviser)
    return LlmStageClient(router=_router_from_pool(pool), prompt_path_default=prompt)


def get_stage_client_editor() -> LlmStageClient:
    cfg = get_editorial_config()
    prompts_dir = _resolve_prompts_dir()
    prompt = str(Path(prompts_dir) / "editor.md")
    pool = _pool_or_fallback(cfg.llm.reviser, cfg.llm.reporter)
    return LlmStageClient(router=_router_from_pool(pool), prompt_path_default=prompt)


if __name__ == "__main__":
    client = get_stage_client_reporter()
    out = client.run_json(
        template_vars={
            "TITULO": "Teste",
            "CORPO": "Texto",
            "KEYWORDS": "",
            "SITE_NAME": "demo",
            "ACT_TYPE": "demo",
        },
        allowed_keys=["titulo", "texto_completo_md"],
        corr_id="demo",
        prompt_path="configs/prompts/reporter.md",
    )
    print(out.ok, out.provider, out.model, bool(out.parsed_json))
