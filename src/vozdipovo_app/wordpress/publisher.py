#!filepath: src/vozdipovo_app/wordpress/publisher.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from vozdipovo_app.category_registry import resolve_category_id, sanitize_category
from vozdipovo_app.wordpress.client import WordPressClient


def upsert_post(
    title: str,
    content_md: str,
    keywords: Union[str, Sequence[str]],
    categoria_tematica: str,
    subcategoria: str = "",
    existing_post_id: Optional[int] = None,
    default_status: str = "publish",
) -> Tuple[int, str]:
    categoria = sanitize_category(categoria_tematica)
    cat_id = resolve_category_id(categoria)
    tags = _normalize_tags(keywords)

    client = WordPressClient()
    payload: Dict[str, Any] = {
        "title": title,
        "content": content_md,
        "status": default_status,
        "categories": [cat_id],
    }
    if tags:
        payload["tags"] = client.ensure_tags(tags)

    if existing_post_id:
        post = client.update_post(existing_post_id, payload)
    else:
        post = client.create_post(payload)

    post_id = int(post.get("id") or 0)
    link = str(post.get("link") or "").strip()
    return post_id, link


def _normalize_tags(keywords: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(keywords, str):
        parts = [p.strip() for p in keywords.split(",") if p.strip()]
        return _dedupe(parts)
    return _dedupe([str(x).strip() for x in keywords if str(x).strip()])


def _dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for it in items:
        k = it.casefold()
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out
