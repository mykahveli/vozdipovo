#!filepath: src/vozdipovo_app/tui/app.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from vozdipovo_app.tui.log_buffer import LogBuffer
from vozdipovo_app.tui.runner import SubprocessStageRunner
from vozdipovo_app.tui.settings import TuiSettings
from vozdipovo_app.utils.logging_config import configure_logging


@dataclass(slots=True)
class StageState:
    """Represents a stage in the TUI."""

    name: str
    status: str = "idle"
    last_code: Optional[int] = None
    last_finished_utc: Optional[datetime] = None


class VozDiPovoTui:
    """Full screen TUI for monitoring and running pipeline stages."""

    def __init__(self, settings: Optional[TuiSettings] = None) -> None:
        self._settings = settings or TuiSettings()
        self._buf = LogBuffer(max_lines=int(self._settings.max_log_lines))
        self._stages: List[StageState] = [StageState(name=n) for n in self._default_stages()]
        self._selected = 0
        self._running = False
        self._last_activity_utc: datetime = datetime.now(tz=timezone.utc)
        self._runner = SubprocessStageRunner(
            repo_root=self._settings.repo_root,
            script_path=self._settings.run_script,
            log_buffer=self._buf,
        )

        configure_logging(enable_console=False)

        self._kb = self._build_key_bindings()
        self._style = self._build_style()
        self._header = Window(height=1, content=FormattedTextControl(self._render_header))
        self._footer = Window(height=1, content=FormattedTextControl(self._render_footer))
        self._stage_panel = Window(width=32, content=FormattedTextControl(self._render_stage_list))
        self._log_panel = Window(content=FormattedTextControl(self._render_logs))

        self._layout = Layout(
            HSplit([self._header, VSplit([self._stage_panel, self._log_panel]), self._footer])
        )
        self._app: Application = Application(
            layout=self._layout,
            key_bindings=self._kb,
            full_screen=True,
            mouse_support=True,
            style=self._style,
        )

    @property
    def settings(self) -> TuiSettings:
        return self._settings

    def run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        refresh = max(50, int(self._settings.refresh_ms)) / 1000.0
        self._buf.append("TUI iniciado")
        ui_task = asyncio.create_task(self._ticker(refresh))
        try:
            await self._app.run_async()
        finally:
            ui_task.cancel()
            with contextlib.suppress(Exception):
                await ui_task

    async def _ticker(self, refresh_seconds: float) -> None:
        while True:
            await asyncio.sleep(refresh_seconds)
            self._app.invalidate()

    def _default_stages(self) -> List[str]:
        return ["scraping", "judging", "curation", "generation", "revision", "publishing", "audio"]

    def _build_style(self) -> Style:
        return Style.from_dict(
            {
                "header": "reverse",
                "footer": "reverse",
                "stage.selected": "bold",
                "stage.running": "fg:#00ff00",
                "stage.failed": "fg:#ff0000",
                "stage.done": "fg:#00ffff",
            }
        )

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("q")
        @kb.add("c-c")
        def _(event) -> None:
            event.app.exit()

        @kb.add("j")
        def _(event) -> None:
            self._selected = min(self._selected + 1, len(self._stages) - 1)
            event.app.invalidate()

        @kb.add("k")
        def _(event) -> None:
            self._selected = max(self._selected - 1, 0)
            event.app.invalidate()

        @kb.add("c")
        def _(event) -> None:
            self._buf.clear()
            self._touch()
            event.app.invalidate()

        @kb.add("r")
        def _(event) -> None:
            if self._running:
                self._buf.append("Já existe execução em curso")
                self._touch()
                return
            asyncio.create_task(self._run_selected())

        @kb.add("a")
        def _(event) -> None:
            if self._running:
                self._buf.append("Já existe execução em curso")
                self._touch()
                return
            asyncio.create_task(self._run_all())

        return kb

    async def _run_selected(self) -> None:
        stage = self._stages[self._selected]
        await self._run_stage(stage.name)

    async def _run_all(self) -> None:
        for s in self._stages:
            await self._run_stage(s.name)

    async def _run_stage(self, stage_name: str) -> None:
        self._running = True
        self._set_status(stage_name, "running", None)
        self._buf.append(f"Stage a iniciar: {stage_name}")
        self._touch()
        try:
            res = await self._runner.run_stage(stage_name)
            status = "done" if res.return_code == 0 else "failed"
            self._set_status(stage_name, status, res.return_code)
            self._buf.append(f"Stage terminou: {stage_name} code={res.return_code}")
        except Exception as e:
            self._set_status(stage_name, "failed", 2)
            self._buf.append(f"ERRO: exceção na execução: {e}")
        finally:
            self._running = False
            self._touch()
            self._app.invalidate()

    def _set_status(self, stage_name: str, status: str, code: Optional[int]) -> None:
        for s in self._stages:
            if s.name == stage_name:
                s.status = status
                s.last_code = code
                s.last_finished_utc = (
                    datetime.now(tz=timezone.utc) if status in {"done", "failed"} else None
                )
                break

    def _touch(self) -> None:
        self._last_activity_utc = datetime.now(tz=timezone.utc)

    def _render_header(self) -> ANSI:
        now = datetime.now(tz=timezone.utc).strftime("%H:%M:%S UTC")
        root = str(Path(self._settings.repo_root).resolve())
        text = f" VozDiPovo TUI  {now}  root={root} "
        return ANSI(text)

    def _render_footer(self) -> ANSI:
        idle_s = int((datetime.now(tz=timezone.utc) - self._last_activity_utc).total_seconds())
        sel = self._stages[self._selected].name if self._stages else "n/a"
        running = "sim" if self._running else "não"
        text = f" q sair, j k navegar, r correr stage, a correr tudo, c limpar logs  selecionado={sel}  executando={running}  idle={idle_s}s "
        return ANSI(text)

    def _render_stage_list(self) -> List[Tuple[str, str]]:
        lines: List[Tuple[str, str]] = []
        for i, st in enumerate(self._stages):
            style = "class:stage.selected" if i == self._selected else ""
            if st.status == "running":
                style = "class:stage.running"
            if st.status == "failed":
                style = "class:stage.failed"
            if st.status == "done":
                style = "class:stage.done"
            suffix = f" [{st.status}]"
            if st.last_code is not None:
                suffix += f" code={st.last_code}"
            lines.append((style, f"{st.name}{suffix}\n"))
        return lines

    def _render_logs(self) -> ANSI:
        self._touch()
        return ANSI(self._buf.as_text())


def run_tui() -> None:
    VozDiPovoTui().run()
