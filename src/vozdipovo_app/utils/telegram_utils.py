# src/vozdipovo_app/utils/telegram_utils.py
import logging
import os

import requests

from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


def send_telegram_msg(message: str):
    """Envia uma mensagem síncrona para o Telegram (Fire-and-forget)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        # Silencioso se não configurado
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

    try:
        # Timeout muito curto (3s) para não encravar o bot se houver problemas de DNS
        requests.post(url, json=payload, timeout=3.0)
    except requests.exceptions.RequestException as e:
        # Log apenas como warning e não erro crítico para não poluir o log de erros
        logger.warning(f"Telegram falhou (DNS/Rede): {e}")
    except Exception as e:
        logger.warning(f"Telegram falhou (Genérico): {e}")
