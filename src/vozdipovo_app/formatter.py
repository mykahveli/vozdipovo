#!filepath: src/vozdipovo_app/formatter.py
from __future__ import annotations

from typing import Mapping, Sequence


def format_chat_prompt(messages: Sequence[Mapping[str, str]], enable_thinking: bool = False) -> str:
    """Format chat messages into a single model prompt.

    Args:
        messages: Sequence of mappings with keys role and content.
        enable_thinking: Whether to request deliberation.

    Returns:
        str: Formatted prompt string.
    """
    parts: list[str] = ["<s>"]
    sys_msgs = [m.get("content", "") for m in messages if m.get("role") == "system"]
    if sys_msgs:
        parts.append(f"<|system_start|>{sys_msgs[-1]}<|system_end|>")
    deliberation = "enabled" if enable_thinking else "disabled"
    parts.append(
        f"<|developer_start|>Deliberation: {deliberation}\nTool Capabilities: disabled<|developer_end|>"
    )
    for m in messages:
        role = str(m.get("role", "")).strip()
        content = str(m.get("content", ""))
        if role == "user":
            parts.append(f"<|user_start|>{content}<|user_end|>")
        elif role == "assistant":
            parts.append(f"<|assistant_start|>{content}")
    return "".join(parts)


def build_user_prompt(instructions: str, text_body: str) -> str:
    """Build a user prompt by inserting the text body into instructions.

    Args:
        instructions: Prompt template text.
        text_body: Body to insert.

    Returns:
        str: Final user prompt.
    """
    return str(instructions or "").replace("{{TEXTO}}", str(text_body or ""))
