#!filepath: src/vozdipovo_app/modules/audio_stage.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Set

from vozdipovo_app.audio_generator import gerar_audio_para_artigo
from vozdipovo_app.modules.base import Stage, StageContext
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


def _highlights_set(values: Sequence[str]) -> Set[str]:
    return {str(v or "").strip().upper() for v in values if str(v or "").strip()}


@dataclass(frozen=True, slots=True)
class AudioStage(Stage):
    """Generate audio only for highlighted posts."""

    ctx: StageContext
    enabled: bool
    only_for_highlights: bool
    highlight_types: Set[str]
    output_subdir: str
    limit: int = 50

    def run(self) -> int:
        if not self.enabled:
            return 0

        conn = self.ctx.conn
        out_dir = (
            Path(str(self.ctx.app_cfg["paths"].get("data_root", "data")))
            / self.output_subdir
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        rows = conn.execute(
            """
            SELECT legal_doc_id, highlight_type, audio_filepath, titulo, corpo_md
            FROM news_articles
            WHERE publishing_status='SUCCESS'
              AND wp_post_id IS NOT NULL
            ORDER BY score_editorial DESC, published_at DESC
            LIMIT ?
            """,
            (self.limit,),
        ).fetchall()

        done = 0
        for r in rows:
            legal_doc_id = int(r["legal_doc_id"])
            highlight_type = str(r["highlight_type"] or "").strip().upper()
            audio_fp = str(r["audio_filepath"] or "").strip()

            if self.only_for_highlights and highlight_type not in self.highlight_types:
                if r["audio_filepath"] is not None:
                    conn.execute(
                        "UPDATE news_articles SET audio_filepath=NULL WHERE legal_doc_id=?",
                        (legal_doc_id,),
                    )
                    conn.commit()
                continue

            if audio_fp:
                continue

            titulo = str(r["titulo"] or "").strip()
            corpo = str(r["corpo_md"] or "").strip()
            if not corpo:
                continue

            texto_audio = f"{titulo}. {corpo}" if titulo else corpo
            fp = gerar_audio_para_artigo(
                texto_audio, str(out_dir), f"article_{legal_doc_id}"
            )
            if fp:
                conn.execute(
                    "UPDATE news_articles SET audio_filepath=? WHERE legal_doc_id=?",
                    (fp, legal_doc_id),
                )
                conn.commit()
                done += 1
            else:
                logger.error(f"Falha ao gerar áudio: legal_doc_id={legal_doc_id}")

        return done
