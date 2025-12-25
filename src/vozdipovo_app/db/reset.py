#!src/vozdipovo_app/db/reset.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from vozdipovo_app.db.migrate import recreate_schema
from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ResetResult:
    """Resultado do reset destrutivo.

    Attributes:
        ok: Se concluiu.
        db_path: Caminho resolvido.
        removed_file: Se removeu ficheiro existente.
    """

    ok: bool
    db_path: Path
    removed_file: bool


def reset_database_file(db_path: Union[str, Path]) -> ResetResult:
    """Apaga o ficheiro sqlite e recria schema.

    Args:
        db_path: Caminho para o ficheiro sqlite.

    Returns:
        ResetResult: Resultado.
    """
    p = Path(db_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    removed = False
    if p.exists():
        try:
            os.remove(p)
            removed = True
            logger.warning(f"Ficheiro da base removido, path={p}")
        except OSError as e:
            logger.error(f"Falha ao remover base, path={p}, err={e}")
            return ResetResult(ok=False, db_path=p, removed_file=False)

    conn = recreate_schema(p)
    conn.close()
    return ResetResult(ok=True, db_path=p, removed_file=removed)
