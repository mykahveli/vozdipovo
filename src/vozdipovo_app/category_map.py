#!filepath: src/vozdipovo_app/category_map.py
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, Set

DEFAULT_CATEGORY_ALIASES: Dict[str, str] = {
    "economia": "Economia",
    "negocios": "Economia",
    "economia e negocios": "Economia",
    "economia/negocios": "Economia",
    "ciencia": "Ciência",
    "desporto": "Desporto",
    "desporte": "Desporto",
    "politica": "Política",
    "saude": "Saúde",
    "sociedade": "Sociedade",
    "tecnologia": "Tecnologia",
    "internacional": "Internacional",
    "cultura": "Cultura",
    "lifestyle": "Lifestyle",
    "estilo de vida": "Lifestyle",
    "casos do dia": "Casos do Dia",
    "outras": "Outras",
    "geral": "Geral",
    "sem categoria": "Geral",
    "desconhecido": "Geral",
    "indefinido": "Geral",
    "breaking": "Breaking News",
    "breaking news": "Breaking News",
    "featured": "Featured Stories",
    "featured stories": "Featured Stories",
}


@dataclass(frozen=True, slots=True)
class CategoryNormalizer:
    """Normalize and canonicalize category names produced by models."""

    allowed_categories: Set[str]
    aliases: Dict[str, str]
    fallback: str = "Geral"

    @staticmethod
    def _fold(s: str) -> str:
        raw = (s or "").strip()
        if not raw:
            return ""
        norm = unicodedata.normalize("NFKD", raw)
        norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
        norm = " ".join(norm.split()).casefold()
        return norm

    def canonical(self, name: str) -> str:
        """Return canonical category name or fallback.

        Args:
            name: Raw category name.

        Returns:
            str: Canonical category.
        """
        folded = self._fold(name)
        if not folded:
            return self.fallback

        alias = self.aliases.get(folded)
        if alias and alias in self.allowed_categories:
            return alias

        for cat in self.allowed_categories:
            if self._fold(cat) == folded:
                return cat

        return self.fallback


def build_normalizer(allowed_categories: Iterable[str]) -> CategoryNormalizer:
    """Build a CategoryNormalizer from the allowed category names.

    Args:
        allowed_categories: Iterable of allowed canonical categories.

    Returns:
        CategoryNormalizer: Normalizer instance.
    """
    allowed = {str(x).strip() for x in allowed_categories if str(x).strip()}
    if "Geral" not in allowed:
        allowed.add("Geral")
    return CategoryNormalizer(
        allowed_categories=allowed, aliases=dict(DEFAULT_CATEGORY_ALIASES)
    )
