#!filepath: src/vozdipovo_app/category_rules.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CategoryContext:
    """Context used to resolve thematic categories.

    Args:
        site_name: Scraper site identifier (e.g., "bo_cv", "governo_cv").
        act_type: Document type from the source (may be empty).
    """

    site_name: str
    act_type: str = ""


def resolve_seed_category(ctx: CategoryContext, *, default: str = "Geral") -> str:
    """Return a deterministic seed category used at judging time.

    This prevents official sources from being stuck in 'Geral' while only JUDGED.

    Args:
        ctx: Category context.
        default: Fallback category.

    Returns:
        str: Category name.
    """
    site = (ctx.site_name or "").strip().casefold()

    if site == "bo_cv":
        return "Legislação"

    if site == "governo_cv":
        return "Política"

    return default


def resolve_categoria_tematica(
    ctx: CategoryContext,
    *,
    model_category: str,
    draft_category: str,
    fallback: str = "Geral",
) -> str:
    """Resolve the final category with deterministic fallbacks.

    Rules:
    - bo_cv => Legislação (always)
    - governo_cv => model > draft > Política
    - otherwise => model > draft > fallback

    Args:
        ctx: Category context.
        model_category: Category produced by reviser.
        draft_category: Category produced by generator.
        fallback: Final fallback category.

    Returns:
        str: Final category name.
    """
    site = (ctx.site_name or "").strip().casefold()

    m = (model_category or "").strip()
    d = (draft_category or "").strip()

    if site == "bo_cv":
        return "Legislação"

    if site == "governo_cv":
        return m or d or "Política"

    return m or d or fallback
