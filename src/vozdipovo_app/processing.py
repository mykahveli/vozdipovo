#!filepath: src/vozdipovo_app/processing.py
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from vozdipovo_app.api_client import call_publicai
from vozdipovo_app.database import (
    already_processed,
    ensure_db,
    insert_row,
    sha256_text,
    update_row_response,
)
from vozdipovo_app.formatter import build_user_prompt, format_chat_prompt
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BatchStats:
    """Batch processing stats.

    Args:
        ok: Number of successful items.
        error: Number of failed items.
        skip: Number of skipped items.
    """

    ok: int
    error: int
    skip: int

    def as_dict(self) -> dict[str, int]:
        """Convert stats to dict.

        Returns:
            dict[str, int]: Stats mapping.
        """
        return {"ok": int(self.ok), "error": int(self.error), "skip": int(self.skip)}


def process_batch(
    cfg: Mapping[str, Any],
    only: Optional[str] = None,
    limit: int = 0,
    reprocess: bool = False,
    export_md: bool = False,
) -> dict[str, int]:
    """Process a batch of text files using the configured API client.

    Args:
        cfg: App config mapping.
        only: Optional filename filter.
        limit: Optional max files to process.
        reprocess: Whether to reprocess already processed files.
        export_md: Whether to export markdown reports.

    Returns:
        dict[str, int]: Batch stats.
    """
    paths = cfg.get("paths", {})
    textos_dir = Path(str(paths.get("textos", "")))
    prompt_file = Path(str(paths.get("prompt", "")))
    db_path = str(paths.get("db", ""))
    out_md = str(paths.get("out_markdown", ""))

    if not prompt_file.exists():
        raise SystemExit(f"Prompt file não encontrado: {prompt_file}")

    instructions = prompt_file.read_text(encoding="utf8")
    conn = ensure_db(db_path)

    files = sorted(textos_dir.glob("*.txt"))
    if only:
        files = [f for f in files if f.name == only]
    if limit > 0:
        files = files[:limit]

    if not files:
        logger.warning(f"Nenhum txt encontrado em {textos_dir}")
        return BatchStats(ok=0, error=0, skip=0).as_dict()

    stats = BatchStats(ok=0, error=0, skip=0)

    for path in files:
        content = path.read_text(encoding="utf8")
        file_hash = sha256_text(f"{path.name}|{content}")
        mtime = path.stat().st_mtime
        created_at = dt.datetime.fromtimestamp(mtime).isoformat(timespec="seconds")

        if (not reprocess) and already_processed(conn, file_hash):
            logger.info(f"Skip, já processado, file={path.name}")
            stats = BatchStats(ok=stats.ok, error=stats.error, skip=stats.skip + 1)
            continue

        messages: list[dict[str, str]] = []
        sys_msg = str(cfg.get("system_message") or "")
        if sys_msg:
            messages.append({"role": "system", "content": sys_msg})

        user_content = build_user_prompt(instructions, content)
        messages.append({"role": "user", "content": user_content})

        formatted_prompt = format_chat_prompt(
            messages, enable_thinking=bool(cfg.get("thinking", False))
        )

        if reprocess and already_processed(conn, file_hash):
            conn.execute("DELETE FROM processed_texts WHERE file_hash = ?", (file_hash,))
            conn.commit()

        api_cfg = cfg.get("api", {})
        row = {
            "filename": path.name,
            "created_at": created_at,
            "file_mtime": mtime,
            "file_hash": file_hash,
            "content_text": content,
            "prompt_used": formatted_prompt,
            "response_text": None,
            "status": "pending",
            "error": None,
            "model": api_cfg.get("model", ""),
            "api_version": api_cfg.get("version", ""),
            "temperature": float(api_cfg.get("temperature", 0.0)),
            "top_p": float(api_cfg.get("top_p", 1.0)),
            "max_tokens": int(api_cfg.get("max_tokens", 0)),
            "usage_prompt_tokens": None,
            "usage_completion_tokens": None,
            "usage_total_tokens": None,
        }
        row_id = insert_row(conn, row)

        try:
            data = call_publicai(
                api_key=str(cfg.get("api_key", "")),
                model=str(row["model"]),
                prompt=formatted_prompt,
                max_tokens=int(row["max_tokens"]),
                temperature=float(row["temperature"]),
                top_p=float(row["top_p"]),
                api_version=str(row["api_version"]),
                user_agent=str(api_cfg.get("user_agent", "")),
            )
            assistant_text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            update_row_response(conn, row_id, assistant_text, status="ok", usage=usage, error=None)
            logger.info(f"Ok, file={path.name}")
            stats = BatchStats(ok=stats.ok + 1, error=stats.error, skip=stats.skip)

            if export_md:
                from vozdipovo_app.exporter import export_markdown_one

                export_markdown_one(
                    out_dir=out_md,
                    filename=path.name,
                    original_text=content,
                    response_text=assistant_text,
                    prompt_used=formatted_prompt,
                )

        except Exception as e:
            update_row_response(
                conn, row_id, response_text=None, status="error", usage=None, error=str(e)
            )
            logger.error(f"Erro, file={path.name}, err={e}", exc_info=True)
            stats = BatchStats(ok=stats.ok, error=stats.error + 1, skip=stats.skip)

    return stats.as_dict()
