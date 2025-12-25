#!filepath: src/vozdipovo_app/llm/openrouter_client.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from vozdipovo_app.llm.http_transport import HTTPTransport
from vozdipovo_app.llm.models import ChatRequest, ChatResponse
from vozdipovo_app.llm.settings import OpenRouterSettings


@dataclass(frozen=True, slots=True)
class OpenRouterClient:
    """OpenRouter chat client."""

    settings: OpenRouterSettings

    def chat(self, req: ChatRequest) -> ChatResponse:
        model = str(req.model or "").strip()
        if not model:
            raise ValueError("model em falta no ChatRequest")

        h = chr(45)
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            f"Content{h}Type": "application/json",
        }
        if self.settings.http_referer.strip():
            headers[f"HTTP{h}Referer"] = self.settings.http_referer.strip()
        if self.settings.app_title.strip():
            headers[f"X{h}Title"] = self.settings.app_title.strip()

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "temperature": float(req.temperature),
        }
        if req.max_tokens is not None:
            payload["max_tokens"] = int(req.max_tokens)
        if req.top_p is not None:
            payload["top_p"] = float(req.top_p)
        if req.response_format is not None:
            payload["response_format"] = dict(req.response_format)
        if req.extra:
            payload.update(dict(req.extra))

        t = HTTPTransport(timeout_seconds=int(self.settings.timeout_seconds))
        data = t.post_json(
            url=f"{self.settings.base_url}/chat/completions",
            headers=headers,
            payload=payload,
            provider="openrouter",
            model=model,
        )

        content = str(
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        ).strip()
        return ChatResponse(content=content, provider="openrouter", model=model, raw=data)
