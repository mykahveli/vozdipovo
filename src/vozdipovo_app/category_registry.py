#!filepath: src/vozdipovo_app/category_registry.py
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List

from vozdipovo_app.editorial.config import get_editorial_config


@dataclass(frozen=True, slots=True)
class CategoryRegistry:
    """Registry for canonical category names and WordPress category ids.

    Args:
        category_ids: Mapping of canonical category name to WordPress category id.
        allowed_editorial_categories: Allowed editorial categories, empty means all in category_ids.
        aliases: Mapping of folded alias to canonical category name.
    """

    category_ids: Dict[str, int]
    allowed_editorial_categories: List[str]
    aliases: Dict[str, str]

    @staticmethod
    def _fold(s: str) -> str:
        t = (s or "").strip()
        if not t:
            return ""
        t = unicodedata.normalize("NFKD", t)
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        t = " ".join(t.split()).casefold()
        return t

    def canonical(self, name: str) -> str:
        """Return canonical category name.

        Args:
            name: Raw category name.

        Returns:
            str: Canonical category name, defaults to Geral.
        """
        folded = self._fold(name)
        if not folded:
            return "Geral"
        if folded in self.aliases:
            return self.aliases[folded]
        for k in self.category_ids.keys():
            if self._fold(k) == folded:
                return k
        return "Geral"

    def id_for(self, name: str) -> int:
        """Return WordPress category id for a category name.

        Args:
            name: Raw category name.

        Returns:
            int: WordPress category id, defaults to Geral, or 1.
        """
        canonical = self.canonical(name)
        return int(self.category_ids.get(canonical, self.category_ids.get("Geral", 1)))

    def normalize_editorial_category(self, value: str) -> str:
        """Normalize an editorial category, enforcing allowed set.

        Args:
            value: Raw category.

        Returns:
            str: Canonical category if allowed, otherwise empty string.
        """
        canonical = self.canonical(value)
        allowed = (
            set(self.allowed_editorial_categories)
            if self.allowed_editorial_categories
            else set(self.category_ids.keys())
        )
        return canonical if canonical in allowed else ""


@lru_cache(maxsize=1)
def get_category_registry() -> CategoryRegistry:
    cfg = get_editorial_config()
    wp = cfg.wordpress

    aliases = {
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

    return CategoryRegistry(
        category_ids=dict(wp.category_ids),
        allowed_editorial_categories=list(wp.allowed_editorial_categories),
        aliases=aliases,
    )


def sanitize_category(value: str, fallback: str = "Geral") -> str:
    """Sanitize a category to a canonical name known by the registry.

    Args:
        value: Raw category string.
        fallback: Fallback canonical category when value is invalid.

    Returns:
        str: Canonical category name.
    """
    reg = get_category_registry()
    name = reg.canonical(value)
    return name if name in reg.category_ids else reg.canonical(fallback)


def resolve_category_id(value: str, fallback: str = "Geral") -> int:
    """Resolve a WordPress category id from a raw category string.

    Args:
        value: Raw category string.
        fallback: Fallback canonical category when value is invalid.

    Returns:
        int: WordPress category id.
    """
    reg = get_category_registry()
    canonical = sanitize_category(value, fallback=fallback)
    return reg.id_for(canonical)
