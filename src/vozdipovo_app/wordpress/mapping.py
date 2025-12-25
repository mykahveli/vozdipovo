#!filepath: src/vozdipovo_app/wordpress/mapping.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class PostPayload:
    """WordPress post payload."""

    title: str
    body_md: str
    status: str
    categories: List[int]
    tags: List[int]
    pub_date: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None

    @property
    def content(self) -> str:
        return self.body_md

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "title": self.title,
            "content": self.content,
            "status": self.status,
            "categories": self.categories,
            "tags": self.tags,
        }
        if self.pub_date:
            data["date"] = self.pub_date
        if self.meta:
            data["meta"] = self.meta
        return data
