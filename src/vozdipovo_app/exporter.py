#!filepath: src/vozdipovo_app/exporter.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExportPaths:
    """Export output paths.

    Args:
        markdown_path: Markdown file path.
        index_path: Index path.
    """

    markdown_path: Path
    index_path: Path


def export_markdown_one(
    out_dir: str,
    filename: str,
    original_text: str,
    response_text: str,
    prompt_used: str,
) -> Path:
    """Export a single markdown report.

    Args:
        out_dir: Output directory.
        filename: Base filename.
        original_text: Original content.
        response_text: Model response.
        prompt_used: Prompt used.

    Returns:
        Path: Path to the generated markdown file.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    md_path = out / (str(filename) + ".md")
    md: list[str] = []
    md.append(f"# Relatório: {filename}\n")
    md.append("## Texto original\n")
    md.append("```\n" + (original_text or "").strip() + "\n```\n")
    md.append("## Prompt usado\n")
    md.append("```\n" + (prompt_used or "").strip() + "\n```\n")
    md.append("## Resposta do modelo\n")
    md.append((response_text or "").strip() + "\n")
    md_path.write_text("\n".join(md), encoding="utf8")
    return md_path


def export_markdown_index(out_dir: str) -> Path:
    """Export a markdown index listing all reports.

    Args:
        out_dir: Output directory.

    Returns:
        Path: Path to index markdown.
    """
    out = Path(out_dir)
    items = sorted([p for p in out.glob("*.md") if p.name != "index.md"])
    lines: list[str] = ["# Índice de Relatórios", ""]
    for p in items:
        lines.append(f"* [{p.stem}]({p.name})")
    index_path = out / "index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf8")
    return index_path
