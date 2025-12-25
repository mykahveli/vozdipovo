#!filepath: src/vozdipovo_app/utils/warnings_config.py
from __future__ import annotations

import warnings


def configure_warnings() -> None:
    """Configure warning filters for third-party libs.

    This suppresses known noisy SyntaxWarnings emitted by pydub on Python 3.12+.
    """
    warnings.filterwarnings(
        "ignore",
        category=SyntaxWarning,
        module=r"^pydub\.utils$",
    )
    warnings.filterwarnings(
        "ignore",
        category=SyntaxWarning,
        module=r"^pydub(\..*)?$",
    )
