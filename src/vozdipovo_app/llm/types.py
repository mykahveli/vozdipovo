#!filepath: src/vozdipovo_app/llm/types.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    GROQ = "groq"
    OPENROUTER = "openrouter"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Model specification for routing and failover."""

    provider: LLMProvider
    model: str
    label: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.provider.value}:{self.model}"
