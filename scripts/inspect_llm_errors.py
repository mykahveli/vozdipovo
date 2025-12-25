#!scripts/inspect_llm_errors.py
from __future__ import annotations

import importlib


def main() -> int:
    m = importlib.import_module("vozdipovo_app.llm.errors")
    print(getattr(m, "__file__", ""))
    names = sorted([n for n in dir(m) if "Error" in n or "classify" in n])
    print("\n".join(names))
    has = hasattr(m, "AllModelsUnavailableError")
    print(f"has_AllModelsUnavailableError={has}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
