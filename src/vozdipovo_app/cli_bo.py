from pathlib import Path

import typer
import yaml
from rich import print

from vozdipovo_app.config import load_app_config
from vozdipovo_app.database import ensure_db
from vozdipovo_app.news_pipeline import generate_one
from vozdipovo_app.scraper_bo import SiteCfg, crawl_bcv

app = typer.Typer(help="Boletim Oficial CV: crawl edições/atos e gerar notícia.")


@app.command()
def _sanitize_optioninfo(val, default):
    try:
        from typer.models import OptionInfo

        if isinstance(val, OptionInfo):
            return default
    except:
        pass
    return val if val is not None else default


def crawl(
    config: str = "configs/default.yaml",
    sites_cfg: str = "configs/sites.yaml",
    max_pages: int = typer.Option(None, help="Override: nº de páginas a percorrer"),
    limit_acts: int = typer.Option(
        5, help="Para testes: parar após N atos inseridos (0 = sem limite)"
    ),
    timeout_list: int = typer.Option(12, help="Timeout (s) da listagem"),
    timeout_detail: int = typer.Option(18, help="Timeout (s) das páginas de detalhe"),
    user_agent: str = typer.Option(
        "VozDiPovoNewsBot/0.1 (+testing)", help="User-Agent a usar"
    ),
    verbose: bool = typer.Option(True, help="Imprimir progresso"),
):
    cfg = load_app_config()
    conn = ensure_db(cfg["paths"]["db"])
    y = yaml.safe_load(Path(sites_cfg).read_text(encoding="utf-8"))
    total = {
        "pages": 0,
        "editions": 0,
        "acts_found": 0,
        "inserted": 0,
        "skipped": 0,
        "errors": 0,
    }
    for s in y.get("sites", []):
        scfg = SiteCfg(**s)
        if max_pages is not None:
            scfg.max_pages = max_pages
        stats = crawl_bcv(
            conn,
            scfg,
            limit_acts=limit_acts,
            timeout_list=_sanitize_optioninfo(timeout_list, (10.0, 30.0)),
            timeout_detail=timeout_detail,
            user_agent=_sanitize_optioninfo(
                user_agent, "VozDiPovoBot/1.0 (+https://voz.local)"
            ),
            verbose=verbose,
        )
        for k, v in stats.items():
            total[k] = total.get(k, 0) + v
    print(f"[bold green]Crawl BO concluído[/bold green]: {total}")


@app.command()
def make_news(
    config: str = "configs/default.yaml",
    doc_id: int = typer.Argument(...),
    prompt_file: str = "prompts/news.md",
):
    cfg = load_app_config()
    out = generate_one(cfg, legal_doc_id=doc_id, prompt_path=Path(prompt_file))
    print("[bold]Gerado:[/bold]", out.get("titulo", "(sem título)"))


if __name__ == "__main__":
    app()
