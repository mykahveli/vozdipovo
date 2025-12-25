#!src/vozdipovo_app/llm/rotator.py
from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from vozdipovo_app.llm.errors import AllModelsUnavailableError, LLMError
from vozdipovo_app.llm.groq_client import GroqClient
from vozdipovo_app.llm.models import ChatRequest, ChatResponse, LLMProvider
from vozdipovo_app.llm.openrouter_client import OpenRouterClient
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Model identifier."""

    provider: LLMProvider
    model: str

    @property
    def key(self) -> Tuple[str, str]:
        """Stable map key."""
        return (self.provider.value, self.model)


@dataclass(slots=True)
class LLMRotator:
    """Rotates models with cooldown per model and per provider."""

    groq: GroqClient
    openrouter: Optional[OpenRouterClient]
    models: List[ModelSpec]
    default_cooldown_seconds: int = 120

    _cooldowns_model: Dict[Tuple[str, str], float] = field(default_factory=dict)
    _cooldowns_provider: Dict[str, float] = field(default_factory=dict)
    _disabled: Dict[Tuple[str, str], str] = field(default_factory=dict)
    _last_good: Optional[ModelSpec] = None

    @property
    def cooldown_current(self) -> Dict[str, float]:
        now = time.time()
        out: Dict[str, float] = {}
        for (provider, model), until in self._cooldowns_model.items():
            remaining = float(until) - float(now)
            if remaining > 0.0:
                out[f"{provider}/{model}"] = remaining
        for provider, until in self._cooldowns_provider.items():
            remaining = float(until) - float(now)
            if remaining > 0.0:
                out[f"{provider}"] = remaining
        return out

    def chat(self, req: ChatRequest, *, model: Optional[str] = None) -> ChatResponse:
        preferred = self._resolve_preferred(model)
        ordered = self._ordered_models(preferred=preferred)

        last_err: Optional[str] = None
        last_delay: int = int(self.default_cooldown_seconds)

        prompt_chars = sum(len(m.content or "") for m in req.messages)

        for spec in ordered:
            if self._is_disabled(spec):
                continue
            if self._is_in_cooldown(spec):
                continue

            actual = self._with_model(req=req, model=spec.model)
            t0 = time.perf_counter()
            logger.info(
                f"LLM attempt start, provider={spec.provider.value}, model={spec.model}, messages={len(req.messages)}, prompt_chars={prompt_chars}"
            )
            try:
                resp = self._dispatch(spec, actual)
                dt = operator.sub(time.perf_counter(), t0)
                logger.info(
                    f"LLM attempt ok, provider={spec.provider.value}, model={spec.model}, seconds={dt:.3f}"
                )
                if not str(resp.content or "").strip():
                    raise ValueError("Resposta vazia do LLM")
                self._last_good = spec
                return resp
            except LLMError as e:
                dt = operator.sub(time.perf_counter(), t0)
                d = e.details
                last_err = d.message or str(e)
                delay = int(
                    max(30, d.retry_after_seconds or self.default_cooldown_seconds)
                )
                last_delay = delay
                logger.error(
                    f"LLM attempt fail, provider={spec.provider.value}, model={spec.model}, seconds={dt:.3f}, kind={d.kind.value}, status={d.status_code}, msg={str(last_err or '')[:220]}"
                )
                if d.kind.value == "not_found":
                    self._disable(spec, reason=last_err)
                    logger.warning(
                        f"Modelo desativado na sessão, model={spec.provider.value}/{spec.model}, reason={str(last_err or '')[:180]}"
                    )
                    continue
                if d.kind.value == "rate_limit":
                    self._set_provider_cooldown(spec.provider.value, delay, last_err)
                    continue
                self._set_model_cooldown(spec, delay, last_err)
                continue
            except Exception as e:
                dt = operator.sub(time.perf_counter(), t0)
                last_err = str(e)
                last_delay = int(self.default_cooldown_seconds)
                logger.error(
                    f"LLM attempt crash, provider={spec.provider.value}, model={spec.model}, seconds={dt:.3f}, err={str(last_err or '')[:220]}"
                )
                self._set_model_cooldown(
                    spec, int(self.default_cooldown_seconds), last_err
                )
                continue

        raise AllModelsUnavailableError(
            cooldown_seconds=int(last_delay),
            models=len(ordered),
            last_error=str(last_err or ""),
        )

    def _with_model(self, req: ChatRequest, model: str) -> ChatRequest:
        return ChatRequest(
            model=model,
            messages=req.messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            top_p=req.top_p,
            response_format=req.response_format,
            extra=req.extra,
        )

    def _resolve_preferred(self, model: Optional[str]) -> Optional[ModelSpec]:
        m = str(model or "").strip()
        if not m:
            return None
        for spec in self.models:
            if spec.model == m:
                return spec
        return None

    def _ordered_models(self, *, preferred: Optional[ModelSpec]) -> List[ModelSpec]:
        if preferred and preferred in self.models:
            rest = [m for m in self.models if m != preferred]
            return [preferred] + rest
        if self._last_good and self._last_good in self.models:
            rest = [m for m in self.models if m != self._last_good]
            return [self._last_good] + rest
        return list(self.models)

    def _is_in_cooldown(self, spec: ModelSpec) -> bool:
        now = time.time()
        p_until = self._cooldowns_provider.get(spec.provider.value)
        if p_until and now < float(p_until):
            return True
        until = self._cooldowns_model.get(spec.key)
        if not until:
            return False
        return now < float(until)

    def _is_disabled(self, spec: ModelSpec) -> bool:
        return spec.key in self._disabled

    def _disable(self, spec: ModelSpec, reason: str) -> None:
        self._disabled[spec.key] = str(reason or "")[:220]

    def _set_model_cooldown(self, spec: ModelSpec, seconds: int, reason: str) -> None:
        until = time.time() + max(1.0, float(seconds))
        self._cooldowns_model[spec.key] = until
        logger.warning(
            f"Modelo em cooldown, model={spec.provider.value}/{spec.model}, seconds={int(seconds)}, reason={str(reason or '')[:180]}"
        )

    def _set_provider_cooldown(self, provider: str, seconds: int, reason: str) -> None:
        until = time.time() + max(1.0, float(seconds))
        self._cooldowns_provider[str(provider)] = until
        logger.warning(
            f"Provider em cooldown, provider={provider}, seconds={int(seconds)}, reason={str(reason or '')[:220]}"
        )

    def _dispatch(self, spec: ModelSpec, req: ChatRequest) -> ChatResponse:
        if spec.provider == LLMProvider.GROQ:
            return self.groq.chat(req)
        if spec.provider == LLMProvider.OPENROUTER:
            if not self.openrouter:
                raise RuntimeError("OpenRouterClient não configurado")
            return self.openrouter.chat(req)
        raise RuntimeError(f"Provider não suportado: {spec.provider}")


if __name__ == "__main__":
    print("rotator_loaded")
