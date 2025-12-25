#!filepath: src/vozdipovo_app/prompts/template.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Strict prompt template renderer.

    Placeholders must be uppercase tokens wrapped as {{TOKEN}}.

    Args:
        name: Template identifier used for error messages.
        text: Raw template contents.

    Raises:
        ValueError: If placeholders are missing or left unresolved.
    """

    name: str
    text: str

    @property
    def placeholders(self) -> set[str]:
        """Return the placeholders declared in the template.

        Returns:
            set[str]: Placeholder names without braces.
        """
        return {m.group(1) for m in _PLACEHOLDER_RE.finditer(self.text or "")}

    def render(self, values: Mapping[str, str]) -> str:
        """Render the template using provided placeholder values.

        Args:
            values: Mapping placeholder name to replacement text.

        Returns:
            str: Rendered prompt with no unresolved placeholders.

        Raises:
            ValueError: If any required placeholder is missing, or if unresolved placeholders remain.
        """
        missing = sorted([p for p in self.placeholders if p not in values])
        if missing:
            raise ValueError(
                f"Prompt {self.name} missing values for {', '.join(missing)}"
            )

        out = self.text
        for k, v in values.items():
            out = out.replace(f"{{{{{k}}}}}", str(v or ""))

        leftover = _PLACEHOLDER_RE.search(out or "")
        if leftover:
            raise ValueError(
                f"Prompt {self.name} unresolved placeholder {leftover.group(0)}"
            )

        return out
