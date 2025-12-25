#!filepath: src/vozdipovo_app/llm/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    GROQ = "groq"
    OPENROUTER = "openrouter"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single chat message."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """A provider agnostic chat request.

    Args:
        model: Provider model id.
        messages: Chat messages.
        temperature: Sampling temperature.
        max_tokens: Output token cap.
        top_p: Nucleus sampling.
        response_format: Optional structured output hint.
        extra: Optional provider specific options.
    """

    model: Optional[str] = None
    messages: List[ChatMessage] = None  # type: ignore[assignment]
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    response_format: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """A provider agnostic chat response."""

    content: str
    provider: str
    model: str
    raw: Optional[Dict[str, Any]] = None
