# src/vozdipovo_app/api_client.py

import random
import time
from typing import Any, Dict

import requests

from .utils.logger import get_logger

logger = get_logger(__name__)


def parse_api_error(resp: requests.Response) -> str:
    try:
        return resp.text
    except Exception:
        return f"status={resp.status_code}"


def post_with_retry(
    url: str, headers: Dict[str, str], payload: Dict[str, Any], max_retries: int = 5
) -> requests.Response:
    """
    Faz um POST para uma API com uma estratégia de exponential backoff.
    Robusto para falhas de rede (DNS, Timeout, Connection Refused).
    """
    backoff_delay = 2.0

    for attempt in range(max_retries):
        try:
            # Timeout: (connect=10s, read=60s) - Importante para conexões lentas
            response = requests.post(
                url, headers=headers, json=payload, timeout=(10, 60)
            )

            # Erros de servidor (5xx) ou Rate Limit (429) -> Retry
            if 500 <= response.status_code < 600 or response.status_code == 429:
                response.raise_for_status()

            # Erros de cliente (4xx) -> Falha imediata (ex: prompt muito longo)
            if 400 <= response.status_code < 500 and response.status_code != 429:
                logger.warning(
                    f"⛔ Erro de cliente {response.status_code}. Não haverá novas tentativas."
                )
                return response

            return response

        except requests.exceptions.RequestException as e:
            # Apanha ConnectionError, Timeout, DNS failure, etc.
            logger.warning(
                f"📡 Erro de rede ou HTTP na tentativa {attempt + 1}/{max_retries}: {e}"
            )

            if attempt == max_retries - 1:
                logger.error("❌ Todas as tentativas de chamada à API falharam.")
                raise e

            sleep_time = backoff_delay + random.uniform(0, 1)
            logger.info(
                f"⏳ A aguardar {sleep_time:.2f}s antes da próxima tentativa..."
            )
            time.sleep(sleep_time)

            backoff_delay = min(backoff_delay * 2, 60)

    raise RuntimeError("Loop de retry terminou sem resultado.")


def call_publicai(api_key: str, model: str, prompt: str, **kwargs) -> Dict[str, Any]:
    """
    Prepara e faz a chamada à API da PublicAI.
    """
    url = f"https://api.publicai.co/{kwargs.get('api_version', 'v1')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": kwargs.get("user_agent", "VozDiPovoNewsBot/0.3 (+CV)"),
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": kwargs.get("max_tokens"),
        "temperature": kwargs.get("temperature"),
        "top_p": kwargs.get("top_p"),
        "frequency_penalty": kwargs.get("frequency_penalty", 0.0),
        "presence_penalty": kwargs.get("presence_penalty", 0.0),
    }
    if kwargs.get("structured_json"):
        payload["response_format"] = {"type": "json_object"}

    resp = post_with_retry(url, headers, payload)

    if resp.status_code >= 400:
        raise requests.exceptions.HTTPError(
            f"API error {resp.status_code}: {parse_api_error(resp)}", response=resp
        )

    return resp.json()
