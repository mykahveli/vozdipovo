#!src/vozdipovo_app/llm/stage_client.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from vozdipovo_app.editorial.config import get_editorial_config, resolve_model_pool
from vozdipovo_app.editorial.models import StageModels
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
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


class LlmStageError(RuntimeError):
    """Raised when a stage LLM call fails."""


@dataclass(frozen=True, slots=True)
class StageRunResult:
    """Normalized result of a stage LLM run."""

    content: str
    provider: str
    model: str
    parsed_json: Dict[str, Any]


def _read_prompt_text(path: str) -> str:
    """Read a prompt template from disk.

    Args:
        path: Prompt file path.

    Returns:
        Prompt template text.

    Raises:
        FileNotFoundError: If prompt file does not exist.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Prompt não encontrado: {p}")
    return p.read_text(encoding="utf8")


def _apply_template(template: str, variables: Dict[str, str]) -> str:
    """Apply simple string replacements for template variables.

    Args:
        template: Prompt template text.
        variables: Placeholder variables.

    Returns:
        Rendered prompt text.
    """
    out = template
    for k, v in variables.items():
        out = out.replace(f"{{{{{k}}}}}", v)
    return out


def _extract_first_json_object(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from the response.

    Args:
        text: Raw model response content.

    Returns:
        Parsed JSON object.

    Raises:
        ValueError: If no JSON object is found.
        json.JSONDecodeError: If JSON parsing fails.
    """
    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        return json.loads(s)
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("Resposta não contém JSON objeto")
    return json.loads(m.group(0))


def _warn_on_extra_keys(
    payload: Dict[str, Any], allowed_keys: List[str], stage: str
) -> None:
    """Warn on unexpected keys in a JSON payload.

    Args:
        payload: Parsed JSON payload.
        allowed_keys: Expected keys list.
        stage: Stage name.
    """
    extra = sorted(set(payload.keys()) - set(allowed_keys))
    if extra:
        logger.warning(f"Stage={stage}, JSON contém chaves extra: {extra}")


def _read_int_env(
    name: str, default: int, *, minimum: int = 1, maximum: int = 3600
) -> int:
    """Read an integer environment variable with bounds.

    Args:
        name: Environment variable name.
        default: Default value if missing or invalid.
        minimum: Minimum allowed value.
        maximum: Maximum allowed value.

    Returns:
        Parsed bounded integer.
    """
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return int(default)
    try:
        val = int(raw)
    except Exception:
        return int(default)
    return int(max(minimum, min(maximum, val)))


def _build_rotator(stage_models: StageModels, timeout_seconds: int) -> LLMRotator:
    """Build a rotator for a given stage.

    Args:
        stage_models: Stage model pools.
        timeout_seconds: HTTP timeout seconds.

    Returns:
        Configured LLMRotator.

    Raises:
        LlmStageError: If no models are configured.
    """
    groq = GroqClient(GroqSettings(timeout_seconds=int(timeout_seconds)))

    openrouter: Optional[OpenRouterClient]
    try:
        openrouter = OpenRouterClient(
            OpenRouterSettings(timeout_seconds=int(timeout_seconds))
        )
    except Exception:
        openrouter = None

    specs: List[ModelSpec] = []
    for m in resolve_model_pool(stage_models.groq):
        specs.append(ModelSpec(provider=LLMProvider.GROQ, model=m))

    if openrouter is not None:
        for m in resolve_model_pool(stage_models.openrouter):
            specs.append(ModelSpec(provider=LLMProvider.OPENROUTER, model=m))

    if not specs:
        raise LlmStageError("Nenhum modelo configurado para o stage")

    cooldown = _read_int_env("LLM_COOLDOWN_SECONDS", 120, minimum=5, maximum=3600)
    return LLMRotator(
        groq=groq,
        openrouter=openrouter,
        models=specs,
        default_cooldown_seconds=int(cooldown),
    )


@dataclass(slots=True)
class LlmStageClient:
    """Run a prompt driven JSON task using configured model pools."""

    stage_name: str
    stage_models: StageModels
    prompt_path_env: str
    prompt_path_default: str
    timeout_seconds: int = 35
    temperature: float = 0.2

    _rotator: Optional[LLMRotator] = field(default=None, init=False)

    def _resolve_prompt_path(self) -> str:
        """Resolve the prompt path using env override.

        Returns:
            Prompt file path.
        """
        env_path = str(os.getenv(self.prompt_path_env, "")).strip()
        return env_path or self.prompt_path_default

    def _get_rotator(self) -> LLMRotator:
        """Get or create the stage rotator.

        Returns:
            Cached LLMRotator instance.
        """
        if self._rotator is None:
            self._rotator = _build_rotator(
                self.stage_models, timeout_seconds=int(self.timeout_seconds)
            )
        return self._rotator

    def run_json(
        self, template_vars: Dict[str, str], allowed_keys: List[str]
    ) -> StageRunResult:
        """Run stage prompt and parse JSON response.

        Args:
            template_vars: Variables to inject in the prompt template.
            allowed_keys: JSON keys expected.

        Returns:
            StageRunResult with parsed JSON.
        """
        prompt_path = self._resolve_prompt_path()
        template = _read_prompt_text(prompt_path)
        prompt = _apply_template(template, template_vars)

        req = ChatRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=float(self.temperature),
            response_format={"type": "json_object"},
        )

        rotator = self._get_rotator()
        resp = rotator.chat(req)
        parsed = _extract_first_json_object(resp.content)
        _warn_on_extra_keys(parsed, allowed_keys=allowed_keys, stage=self.stage_name)

        return StageRunResult(
            content=resp.content,
            provider=str(resp.provider),
            model=str(resp.model),
            parsed_json=parsed,
        )


@lru_cache(maxsize=1)
def get_stage_client_director() -> LlmStageClient:
    """Stage client for judging.

    Returns:
        LlmStageClient for director stage.
    """
    cfg = get_editorial_config()
    timeout_seconds = _read_int_env(
        "DIRECTOR_TIMEOUT_SECONDS", 35, minimum=10, maximum=600
    )
    return LlmStageClient(
        stage_name="diretor",
        stage_models=cfg.llm.judge,
        prompt_path_env="DIRECTOR_PROMPT_PATH",
        prompt_path_default="configs/prompts/diretor.md",
        timeout_seconds=int(timeout_seconds),
        temperature=0.1,
    )


@lru_cache(maxsize=1)
def get_stage_client_reporter() -> LlmStageClient:
    """Stage client for generation.

    Returns:
        LlmStageClient for reporter stage.
    """
    cfg = get_editorial_config()
    models = cfg.llm.reporter or cfg.llm.reviser
    timeout_seconds = _read_int_env(
        "REPORTER_TIMEOUT_SECONDS", 60, minimum=10, maximum=600
    )
    return LlmStageClient(
        stage_name="reporter",
        stage_models=models,
        prompt_path_env="REPORTER_PROMPT_PATH",
        prompt_path_default="configs/prompts/reporter.md",
        timeout_seconds=int(timeout_seconds),
        temperature=0.6,
    )


@lru_cache(maxsize=1)
def get_stage_client_editor() -> LlmStageClient:
    """Stage client for revising.

    Returns:
        LlmStageClient for editor stage.
    """
    cfg = get_editorial_config()
    timeout_seconds = _read_int_env(
        "EDITOR_TIMEOUT_SECONDS", 60, minimum=10, maximum=600
    )
    return LlmStageClient(
        stage_name="editor",
        stage_models=cfg.llm.reviser,
        prompt_path_env="EDITOR_PROMPT_PATH",
        prompt_path_default="configs/prompts/editor.md",
        timeout_seconds=int(timeout_seconds),
        temperature=0.3,
    )


if __name__ == "__main__":
    print(get_stage_client_director().timeout_seconds)
