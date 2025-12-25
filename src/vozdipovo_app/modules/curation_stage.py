#!filepath: src/vozdipovo_app/modules/curation_stage.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Sequence, Set

from vozdipovo_app.modules.base import Stage, StageContext
from vozdipovo_app.utils.logger import get_logger
from vozdipovo_app.wordpress.client import WPClient, WPConfig

logger = get_logger(__name__)


def _wp_client(cfg: dict) -> WPClient:
    wp = cfg["wordpress"]
    return WPClient(
        WPConfig(
            base_url=str(wp["base_url"]),
            username=str(wp["username"]),
            app_password=str(wp["app_password"]),
            default_status=str(wp.get("default_status", "publish")),
            timeout=int(wp.get("timeout", 30)),
            rate_sleep=float(wp.get("rate_sleep", 1.0)),
        )
    )


def _winner_rows(
    conn: sqlite3.Connection,
    hours: int,
    threshold: float,
    limit: int,
    exclude_ids: Sequence[int],
) -> List[sqlite3.Row]:
    placeholders = ",".join(["?"] * len(exclude_ids)) if exclude_ids else "0"
    params = [f"-{hours} hours", threshold]
    query = f"""
    SELECT legal_doc_id, wp_post_id
    FROM news_articles
    WHERE publishing_status='SUCCESS'
      AND wp_post_id IS NOT NULL
      AND published_at > datetime('now', ?)
      AND score_editorial >= ?
      AND legal_doc_id NOT IN ({placeholders})
    ORDER BY score_editorial DESC, published_at DESC
    LIMIT {int(limit)}
    """
    if exclude_ids:
        params.extend(list(exclude_ids))
    return conn.execute(query, tuple(params)).fetchall()


def _wp_ids(rows: Sequence[sqlite3.Row]) -> Set[int]:
    out: Set[int] = set()
    for r in rows:
        v = r["wp_post_id"]
        if v is None:
            continue
        try:
            out.add(int(v))
        except Exception:
            continue
    return out


def _posts_in_category(client: WPClient, cat_id: int) -> Set[int]:
    try:
        posts = client.get(
            f"/wp-json/wp/v2/posts?categories={cat_id}&per_page=100&_fields=id"
        )
        return {
            int(p["id"])
            for p in posts
            if isinstance(p, dict) and p.get("id") is not None
        }
    except Exception as e:
        logger.warning(f"Erro ao obter posts da categoria {cat_id}: {e}")
        return set()


def _set_post_categories(
    client: WPClient,
    post_id: int,
    add_cat_id: int | None = None,
    remove_cat_id: int | None = None,
) -> None:
    post = client.get(f"/wp-json/wp/v2/posts/{post_id}?_fields=id,categories")
    current = post.get("categories", [])

    cats = {int(c) for c in current if str(c).isdigit()}

    if remove_cat_id is not None:
        cats.discard(remove_cat_id)

    if add_cat_id is not None:
        cats.add(add_cat_id)

    client.post(
        f"/wp-json/wp/v2/posts/{post_id}",
        json={"categories": sorted(cats)},
    )


def _sync_category(client: WPClient, cat_id: int, winners: Set[int]) -> None:
    in_cat = _posts_in_category(client, cat_id)
    to_remove = sorted(in_cat - winners)
    to_add = sorted(winners - in_cat)

    for pid in to_remove:
        try:
            _set_post_categories(client, pid, remove_cat_id=cat_id)
        except Exception as e:
            logger.warning(f"Erro ao remover post {pid} da categoria {cat_id}: {e}")

    for pid in to_add:
        try:
            _set_post_categories(client, pid, add_cat_id=cat_id)
        except Exception as e:
            logger.warning(f"Erro ao adicionar post {pid} à categoria {cat_id}: {e}")


def _write_highlight_flags(
    conn: sqlite3.Connection, breaking_ids: Sequence[int], featured_ids: Sequence[int]
) -> None:
    conn.execute(
        "UPDATE news_articles SET highlight_type=NULL WHERE highlight_type IN ('BREAKING','FEATURED')"
    )
    if breaking_ids:
        ph = ",".join(["?"] * len(breaking_ids))
        conn.execute(
            f"UPDATE news_articles SET highlight_type='BREAKING' WHERE legal_doc_id IN ({ph})",
            tuple(breaking_ids),
        )
    if featured_ids:
        ph = ",".join(["?"] * len(featured_ids))
        conn.execute(
            f"UPDATE news_articles SET highlight_type='FEATURED' WHERE legal_doc_id IN ({ph})",
            tuple(featured_ids),
        )
    conn.commit()


@dataclass(frozen=True, slots=True)
class CurationStage(Stage):
    """Compute highlights and sync WP highlight categories."""

    ctx: StageContext
    hours: int
    breaking_threshold: float
    breaking_limit: int
    breaking_category_id: int
    featured_threshold: float
    featured_limit: int
    featured_category_id: int

    def run(self) -> int:
        conn = self.ctx.conn
        client = _wp_client(self.ctx.app_cfg)

        breaking_rows = _winner_rows(
            conn,
            self.hours,
            self.breaking_threshold,
            self.breaking_limit,
            exclude_ids=[],
        )
        breaking_ids = [int(r["legal_doc_id"]) for r in breaking_rows]
        featured_rows = _winner_rows(
            conn,
            self.hours,
            self.featured_threshold,
            self.featured_limit,
            exclude_ids=breaking_ids,
        )
        featured_ids = [int(r["legal_doc_id"]) for r in featured_rows]

        _write_highlight_flags(conn, breaking_ids, featured_ids)

        _sync_category(client, self.breaking_category_id, _wp_ids(breaking_rows))
        _sync_category(client, self.featured_category_id, _wp_ids(featured_rows))

        return len(breaking_ids) + len(featured_ids)
