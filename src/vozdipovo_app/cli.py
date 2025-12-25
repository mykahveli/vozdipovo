#!filepath: src/vozdipovo_app/cli.py
import typer

from vozdipovo_app.utils.logger import get_logger

app = typer.Typer()
logger = get_logger(__name__)


@app.command()
def tui() -> None:
    from vozdipovo_app.tui import run_tui

    try:
        run_tui()
    except Exception as e:
        logger.error(f"Falha ao iniciar TUI: {e}")
        raise typer.Exit(code=2) from e
