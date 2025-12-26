#!src/vozdipovo_app/llm/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    GROQ = "groq"
    OPENROUTER = "openrouter"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single chat message.

    Attributes:
        role: Message role, for example user, system, assistant.
        content: Message content.
    """

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """A provider agnostic chat request.

    Attributes:
        model: Provider model id.
        messages: Chat messages.
        temperature: Sampling temperature.
        max_tokens: Max tokens for completion.
        top_p: Nucleus sampling parameter.
        response_format: Provider specific response format options.
        extra: Provider specific options.
    """

    model: Optional[str] = None
    messages: List[ChatMessage] = field(default_factory=list)
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    response_format: Optional[Dict[str, Any]] = None
    extra: Optional[Dict[str, Any]] = None


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """A provider agnostic chat response.

    Attributes:
        content: Text content.
        provider: Provider name.
        model: Model id.
        raw: Optional raw provider response.
    """

    content: str
    provider: str
    model: str
    raw: Optional[Dict[str, Any]] = None


Message = ChatMessage


__all__ = [
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "LLMProvider",
    "Message",
]
