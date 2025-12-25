#!filepath: tests/test_import_contract.py
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ImportContract:
    """A list of import targets that must remain stable.

    Args:
        targets: Import strings to validate.
    """

    targets: tuple[str, ...]


def _contract() -> ImportContract:
    """Build the import contract.

    Returns:
        ImportContract: Contract containing stable import targets.
    """
    return ImportContract(
        targets=(
            "vozdipovo_app",
            "vozdipovo_app.config",
            "vozdipovo_app.settings",
            "vozdipovo_app.editorial.config",
            "vozdipovo_app.editorial.models",
            "vozdipovo_app.modules.scraping_stage",
            "vozdipovo_app.modules.judging_stage",
            "vozdipovo_app.modules.generation_stage",
            "vozdipovo_app.modules.revision_stage",
            "vozdipovo_app.modules.publishing_stage",
            "vozdipovo_app.wordpress.client",
        )
    )


def _import_all(targets: Iterable[str]) -> None:
    """Import all targets.

    Args:
        targets: Module import paths.

    Raises:
        ImportError: If any import fails.
    """
    for t in targets:
        importlib.import_module(t)


def test_import_contract() -> None:
    """Validate that stable import targets remain importable."""
    contract = _contract()
    _import_all(contract.targets)
