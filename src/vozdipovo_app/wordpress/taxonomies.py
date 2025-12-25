#!filepath: src/vozdipovo_app/wordpress/taxonomies.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .client import WPClient


@dataclass(frozen=True, slots=True)
class TermRef:
    """A WordPress taxonomy term reference."""

    id: int
    name: str


def get_or_create_term(client: WPClient, taxonomy: str, name: str) -> Optional[TermRef]:
    """Get or create a WP term for a taxonomy.

    Args:
        client: WordPress REST client.
        taxonomy: Taxonomy name ("tags" supported).
        name: Term name.

    Returns:
        Optional[TermRef]: Term reference or None on failure.
    """
    safe_name = (name or "").strip()
    if not safe_name:
        return None

    endpoint = f"/wp-json/wp/v2/{taxonomy}"
    try:
        existing = client.get(
            f"{endpoint}?search={safe_name}&per_page=100&_fields=id,name"
        )
        for item in existing:
            if str(item.get("name", "")).strip().lower() == safe_name.lower():
                return TermRef(id=int(item["id"]), name=str(item["name"]))
    except Exception:
        pass

    try:
        created = client.post(endpoint, json={"name": safe_name})
        if isinstance(created, dict) and "id" in created:
            return TermRef(
                id=int(created["id"]), name=str(created.get("name", safe_name))
            )
    except Exception:
        return None

    return None
