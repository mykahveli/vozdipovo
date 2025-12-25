# src/vozdipovo_app/utils/debug_utils.py

import datetime as dt
import os
from pathlib import Path


def log_failed_generation(
    legal_doc_id: int, prompt: str, error_message: str, api_response: str | None = None
):
    """
    Guarda os detalhes de uma falha na geração de notícias num ficheiro de log.
    """
    log_dir = Path("data/logs/failed_prompts")
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = log_dir / f"failure_{timestamp}_doc_{legal_doc_id}.log"

    content = f"""--- FALHA NA GERAÇÃO ---
ID do Documento: {legal_doc_id}
Timestamp: {timestamp}
Erro: {error_message}

--- PROMPT ENVIADO ---
{prompt}
"""

    if api_response:
        content += f"""
--- RESPOSTA RECEBIDA DA API ---
{api_response}
"""

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[DEBUG] Detalhes da falha guardados em: {filename}")
