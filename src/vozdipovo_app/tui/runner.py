#!filepath: src/vozdipovo_app/tui/runner.py
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Optional

from vozdipovo_app.tui.log_buffer import LogBuffer


@dataclass(slots=True, frozen=True)
class StageRunResult:
    """Result of a stage execution."""

    stage: str
    return_code: int


class SubprocessStageRunner:
    """Runs pipeline stages as subprocess and streams output."""

    def __init__(self, *, repo_root: Path, script_path: Path, log_buffer: LogBuffer) -> None:
        self._repo_root = repo_root.resolve()
        self._script_path = (self._repo_root / script_path).resolve()
        self._buf = log_buffer

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    @property
    def script_path(self) -> Path:
        return self._script_path

    async def run_stage(self, stage: str) -> StageRunResult:
        if not self._script_path.exists():
            self._buf.append(f"ERRO: script não encontrado: {self._script_path}")
            return StageRunResult(stage=stage, return_code=2)

        cmd = [sys.executable, str(self._script_path), "--stage", str(stage)]
        self._buf.append(f"EXEC: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self._repo_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**dict(**sys.environ), "PYTHONUNBUFFERED": "1"}
                if hasattr(sys, "environ")
                else None,
            )
        except Exception as e:
            self._buf.append(f"ERRO: falha ao iniciar subprocesso: {e}")
            return StageRunResult(stage=stage, return_code=2)

        async def pump(stream: Optional[asyncio.StreamReader], prefix: str) -> None:
            if stream is None:
                return
            async for line in self._read_lines(stream):
                self._buf.append(f"{prefix}{line}")

        await asyncio.gather(pump(proc.stdout, ""), pump(proc.stderr, "STDERR: "))
        code = await proc.wait()
        self._buf.append(f"FIM: stage={stage} code={code}")
        return StageRunResult(stage=stage, return_code=int(code))

    async def _read_lines(self, stream: asyncio.StreamReader) -> AsyncGenerator[str, None]:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            yield raw.decode("utf-8", errors="replace").rstrip("\n")
