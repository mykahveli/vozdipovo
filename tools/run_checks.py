#!filepath: tools/run_checks.py
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Result of a check step.

    Args:
        name: Check name.
        exit_code: Process exit code.
    """

    name: str
    exit_code: int


def run_pytest() -> CheckResult:
    """Run pytest.

    Returns:
        CheckResult: Result for pytest.
    """
    import pytest

    code = int(pytest.main(["tests"]))
    return CheckResult(name="pytest", exit_code=code)


def main() -> int:
    """Run all checks.

    Returns:
        int: Exit code.
    """
    results: List[CheckResult] = [run_pytest()]
    worst = max(r.exit_code for r in results)
    for r in results:
        print(f"{r.name}: {r.exit_code}")
    return int(worst)


if __name__ == "__main__":
    raise SystemExit(main())
