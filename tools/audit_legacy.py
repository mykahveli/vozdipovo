#!filepath: tools/audit_legacy.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Finding:
    """Finding found in the repository.

    Args:
        path: File path.
        lineno: Line number.
        line: Line content.
    """

    path: Path
    lineno: int
    line: str


@dataclass(frozen=True, slots=True)
class AuditResult:
    """Audit results.

    Args:
        findings: All findings.
    """

    findings: tuple[Finding, ...]


class LegacyAuditor:
    """Scan repository for legacy identifiers.

    Args:
        root: Repository root.
        needles: Strings to search for.
    """

    def __init__(self, root: Path, needles: Iterable[str]) -> None:
        self._root = root.resolve()
        self._needles = tuple(str(n) for n in needles if str(n).strip())

    @property
    def root(self) -> Path:
        """Repository root."""
        return self._root

    def run(self) -> AuditResult:
        """Run the audit.

        Returns:
            AuditResult: Findings.
        """
        findings: list[Finding] = []
        for path in self._iter_files():
            findings.extend(self._scan_file(path))
        return AuditResult(findings=tuple(findings))

    def _iter_files(self) -> Iterable[Path]:
        for path in self.root.rglob("*.py"):
            if any(part in {"__pycache__", ".venv"} for part in path.parts):
                continue
            if path.name == "audit_legacy.py":
                continue
            yield path

    def _scan_file(self, path: Path) -> list[Finding]:
        try:
            text = path.read_text(encoding="utf8")
        except OSError:
            return []

        out: list[Finding] = []
        for i, line in enumerate(text.splitlines(), start=1):
            if any(n in line for n in self._needles):
                out.append(Finding(path=path, lineno=i, line=line.rstrip()))
        return out


def main() -> int:
    root = Path.cwd()
    auditor = LegacyAuditor(
        root=root,
        needles=(
            "apertus",
            "Apertus",
            "apertus.",
            "apertus_",
        ),
    )
    result = auditor.run()
    if not result.findings:
        print("ok, sem referências legadas")
        return 0

    for f in result.findings:
        print(f"{f.path}:{f.lineno}:{f.line}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
