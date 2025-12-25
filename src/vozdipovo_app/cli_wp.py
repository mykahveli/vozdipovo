# src/vozdipovo_app/cli_wp.py

from __future__ import annotations

import sqlite3
import time
from typing import Dict

import typer

from .config import load_app_config
from .wordpress.client import WPClient, WPConfig
from .wordpress.publisher import upsert_post

app = typer.Typer(help="CLI WordPress para publicar notícias.")


def _client_from_cfg(cfg) -> WPClient:
    wpcfg = WPConfig(
        base_url=cfg["wordpress"]["base_url"],
        username=cfg["wordpress"]["username"],
        app_password=cfg["wordpress"]["app_password"],
        default_status=cfg["wordpress"].get("default_status", "publish"),
        timeout=int(cfg["wordpress"].get("timeout", 30)),
        rate_sleep=float(cfg["wordpress"].get("rate_sleep", 1.0)),
    )
    return WPClient(wpcfg)


# --- FUNÇÃO "OPERÁRIA" COM A LÓGICA PURA ---
def _do_bulk_publish(
    page_size: int = 10,
    sleep_sec: float = 1.5,
    status: str = "publish",
    max_pages: int = 1,
):
    """
    Esta função contém a lógica de publicação em lote, sem dependências do Typer.
    """
    cfg = load_app_config()
    client = _client_from_cfg(cfg)
    conn = sqlite3.connect(cfg["paths"]["db"])
    page = 0

    try:
        while True:
            # Query que seleciona artigos revistos e pendentes de publicação
            rows = conn.execute(
                """
              SELECT legal_doc_id
              FROM news_articles
              WHERE (review_status = 'SUCCESS' OR review_status IS NULL)
                AND (publishing_status = 'PENDING' OR publishing_status IS NULL)
              ORDER BY legal_doc_id ASC
              LIMIT ? OFFSET ?
            """,
                (page_size, page * page_size),
            ).fetchall()

            if not rows:
                print("Fim: nada mais para publicar.")
                break

            ids = [int(r[0]) for r in rows]
            print(f"Página {page + 1}: {ids}")
            for doc_id in ids:
                try:
                    data = upsert_post(conn, client, doc_id, status=status)
                    print(
                        f"  [ok] {doc_id} -> post {data.get('id')} ({data.get('status')})"
                    )
                except Exception as e:
                    print(f"  [erro] {doc_id}: {e}")
                time.sleep(sleep_sec)

            page += 1
            if max_pages != 0 and page >= max_pages:
                print("A parar por max_pages.")
                break
    finally:
        conn.close()


# --- COMANDOS TYPER (INTERFACE DE LINHA DE COMANDO) ---


@app.command("wp-publish")
def wp_publish(
    doc_id: int = typer.Argument(..., help="legal_doc_id a publicar"),
    status: str = typer.Option("publish", help="status do post: draft|publish|pending"),
):
    cfg = load_app_config()
    client = _client_from_cfg(cfg)
    conn = sqlite3.connect(cfg["paths"]["db"])
    try:
        data = upsert_post(conn, client, doc_id, status=status)
        typer.echo(
            f"[ok] legal_doc_id={doc_id} -> post_id={data.get('id')} ({data.get('status')}) url={data.get('link')}"
        )
    finally:
        conn.close()


@app.command("wp-bulk")
def wp_bulk(
    page_size: int = typer.Option(10, help="quantos por página"),
    sleep_sec: float = typer.Option(1.5, help="intervalo entre posts"),
    status: str = typer.Option("publish", help="status: draft|publish|pending"),
    max_pages: int = typer.Option(1, help="0 = até esgotar"),
):
    """Comando Typer que delega a lógica para a função _do_bulk_publish."""
    _do_bulk_publish(
        page_size=page_size,
        sleep_sec=sleep_sec,
        status=status,
        max_pages=max_pages,
    )


# --- PONTO DE ENTRADA PARA O run_once.py ---
def run():
    """
    Ponto de entrada para a publicação em lote a partir do run_once.py.
    Chama a função de lógica pura com valores padrão concretos.
    """
    print("[Publisher] A iniciar publicação em lote...")
    try:
        _do_bulk_publish(page_size=10, sleep_sec=1.5, status="publish", max_pages=1)
    except Exception as e:
        print(f"[Publisher] Erro durante a publicação em lote: {e}")


if __name__ == "__main__":
    app()
