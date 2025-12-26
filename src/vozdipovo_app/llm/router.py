#!src/vozdipovo_app/llm/router.py
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from vozdipovo_app.llm.errors import LLMError, LLMNonRetryableError, LLMRetryableError
from vozdipovo_app.llm.groq_client import GroqClient, GroqConfig
from vozdipovo_app.llm.openrouter_client import OpenRouterClient, OpenRouterConfig
from vozdipovo_app.llm.types import LLMProvider, ModelSpec
from vozdipovo_app.utils.backoff import call_with_exponential_backoff
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CircuitState:
    """Simple circuit breaker state per model."""

    failed_until_epoch: float = 0.0
    fail_count: int = 0

    @property
    def is_open(self) -> bool:
        return time.time() < self.failed_until_epoch


class LLMRouter:
    """Robust model rotation across providers with sticky preference + circuit breaker."""

    def __init__(self, models: List[ModelSpec]) -> None:
        if not models:
            raise ValueError("LLMRouter requires at least one ModelSpec.")
        self._models = models
        self._sticky: Optional[str] = None
        self._circuits: Dict[str, CircuitState] = {}

        self._groq: Optional[GroqClient] = None
        self._openrouter: Optional[OpenRouterClient] = None

    @staticmethod
    def from_stage_models(models: List[str]) -> "LLMRouter":
        """Cria um router a partir de uma lista de modelos.

        Heurística:
        - Prefixos explícitos: "groq:..." ou "openrouter:..."
        - Sem prefixo: se contiver "/" assume openrouter; caso contrário groq.

        Args:
            models: Lista de strings de modelos.

        Returns:
            LLMRouter: Router configurado.
        """
        specs: List[ModelSpec] = []
        for raw in models:
            s = str(raw or "").strip()
            if not s:
                continue
            provider: LLMProvider
            model = s
            if s.startswith("groq:"):
                provider = LLMProvider.GROQ
                model = s.split(":", 1)[1].strip()
            elif s.startswith("openrouter:"):
                provider = LLMProvider.OPENROUTER
                model = s.split(":", 1)[1].strip()
            elif "/" in s:
                provider = LLMProvider.OPENROUTER
            else:
                provider = LLMProvider.GROQ
            if model:
                specs.append(ModelSpec(provider=provider, model=model))

        if not specs:
            specs = LLMRouter.default_models_for_editorial()
        return LLMRouter(models=specs)

    @staticmethod
    def default_models_for_editorial() -> List[ModelSpec]:
        groq_models = [
            str(os.getenv("JUDGE_MODEL_PRIMARY", "llama-3.3-70b-versatile")).strip(),
            "qwen/qwen3-32b",
            "moonshotai/kimi-k2-instruct-0905",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ]
        openrouter_models = [
            "meta-llama/llama-3.1-405b-instruct:free",
            "nousresearch/hermes-3-llama-3.1-405b:free",
            "openai/gpt-oss-120b:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "qwen/qwen3-coder:free",
        ]

        specs: List[ModelSpec] = []
        specs.extend([ModelSpec(LLMProvider.GROQ, m) for m in groq_models if m])
        specs.extend(
            [ModelSpec(LLMProvider.OPENROUTER, m) for m in openrouter_models if m]
        )
        return specs

    def _get_client(self, provider: LLMProvider) -> Any:
        if provider == LLMProvider.GROQ:
            if self._groq is None:
                self._groq = GroqClient(GroqConfig.from_env())
            return self._groq
        if provider == LLMProvider.OPENROUTER:
            if self._openrouter is None:
                self._openrouter = OpenRouterClient(OpenRouterConfig.from_env())
            return self._openrouter
        raise ValueError(f"Unsupported provider: {provider}")

    def _ordered_models(self) -> List[ModelSpec]:
        models = list(self._models)
        if self._sticky:
            for i, m in enumerate(models):
                if m.key == self._sticky:
                    models.insert(0, models.pop(i))
                    break
        return models

    def _mark_failure(self, spec: ModelSpec, seconds: float) -> None:
        prev = self._circuits.get(spec.key, CircuitState())
        until = max(prev.failed_until_epoch, time.time() + seconds)
        self._circuits[spec.key] = CircuitState(
            failed_until_epoch=until, fail_count=prev.fail_count + 1
        )

    def _is_blocked(self, spec: ModelSpec) -> bool:
        st = self._circuits.get(spec.key)
        return bool(st and st.is_open)

    def chat_json(
        self,
        *,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        purpose: str = "llm",
    ) -> Tuple[str, str]:
        """Call LLM with rotation.

        Args:
            messages: OpenAI-style messages list.
            temperature: Sampling temperature.
            max_tokens: Optional max output tokens.
            purpose: For logging/tracking.

        Returns:
            Tuple[str, str]: (content, model_key_used)
        """
        base_cooldown = float(os.getenv("LLM_CIRCUIT_BASE_COOLDOWN", "20"))
        max_retries = int(os.getenv("LLM_BACKOFF_RETRIES", "3"))

        last_err: Optional[Exception] = None

        for spec in self._ordered_models():
            if self._is_blocked(spec):
                continue

            def _call() -> str:
                client = self._get_client(spec.provider)
                if spec.provider == LLMProvider.GROQ:
                    return client.chat_completions(
                        model=spec.model,
                        messages=messages,
                        temperature=temperature,
                        response_format_json=True,
                        timeout_seconds=int(os.getenv("LLM_TIMEOUT", "30")),
                    )
                return client.chat_completions(
                    model=spec.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format_json=True,
                )

            try:
                content = call_with_exponential_backoff(
                    _call,
                    max_retries=max_retries,
                    base_delay=float(os.getenv("LLM_BACKOFF_BASE_DELAY", "1.0")),
                    max_delay=float(os.getenv("LLM_BACKOFF_MAX_DELAY", "30.0")),
                    is_retryable=lambda e: isinstance(e, LLMRetryableError),
                    on_retry=lambda n, d, e: logger.warning(
                        f"⏳ LLM backoff ({purpose}) {spec.key} retry {n} em {d:.1f}s: {e}"
                    ),
                )
                if self._sticky != spec.key:
                    logger.info(f"🔄 Novo modelo sticky ({purpose}): {spec.key}")
                    self._sticky = spec.key
                return content, spec.key
            except LLMRetryableError as e:
                last_err = e
                self._mark_failure(spec, seconds=base_cooldown)
                if self._sticky == spec.key:
                    self._sticky = None
                logger.warning(f"⚠️ LLM retryable ({purpose}) {spec.key}: {e}")
                continue
            except LLMNonRetryableError as e:
                last_err = e
                self._mark_failure(spec, seconds=base_cooldown * 2)
                if self._sticky == spec.key:
                    self._sticky = None
                logger.warning(f"⛔ LLM non-retryable ({purpose}) {spec.key}: {e}")
                continue
            except Exception as e:
                last_err = e
                self._mark_failure(spec, seconds=base_cooldown)
                if self._sticky == spec.key:
                    self._sticky = None
                logger.warning(f"⚠️ LLM error ({purpose}) {spec.key}: {e}")
                continue

        raise LLMError(
            f"Todos os modelos falharam ({purpose}). Último erro: {last_err}"
        )

    def run_json(
        self,
        *,
        corr_id: str,
        prompt: str,
        force_models: List[str] | None = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        purpose: str = "stage",
    ) -> "JsonRunResult":
        """Executa um prompt que deve devolver JSON.

        Args:
            corr_id: Correlation id (para logs).
            prompt: Prompt final para o LLM.
            force_models: Override de modelos (strings).
            temperature: Sampling.
            max_tokens: Limite tokens.
            purpose: Tag para logging.

        Returns:
            JsonRunResult: Resultado estruturado.
        """
        _ = corr_id

        router = self
        if force_models:
            router = LLMRouter.from_stage_models(force_models)

        try:
            content, model_key = router.chat_json(
                messages=[{"role": "user", "content": str(prompt or "")}],
                temperature=temperature,
                max_tokens=max_tokens,
                purpose=purpose,
            )
        except Exception as e:
            return JsonRunResult(
                ok=False,
                provider="",
                model="",
                text="",
                parsed_json=None,
                error=str(e),
            )

        parsed = _extract_json_object(content)
        provider, model = (model_key.split(":", 1) + [""])[:2]

        if parsed is None:
            return JsonRunResult(
                ok=False,
                provider=provider,
                model=model,
                text=str(content or ""),
                parsed_json=None,
                error="JSON inválido na resposta",
            )

        return JsonRunResult(
            ok=True,
            provider=provider,
            model=model,
            text=str(content or ""),
            parsed_json=parsed,
            error="",
        )


@dataclass(frozen=True, slots=True)
class JsonRunResult:
    """Resultado de uma execução que pretende JSON."""

    ok: bool
    provider: str
    model: str
    text: str
    parsed_json: Dict[str, Any] | None
    error: str


def _extract_json_object(text: str) -> Dict[str, Any] | None:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
