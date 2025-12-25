#!filepath: src/vozdipovo_app/utils/backoff.py
from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Optional


def is_retryable_llm_error(exc: Exception) -> bool:
    """Decide se um erro tende a ser transitório e merece retry.

    Args:
        exc: Exceção capturada.

    Returns:
        True se for razoável tentar novamente.
    """
    s = str(exc).casefold()
    tokens = (
        "429",
        "rate limit",
        "rate_limit",
        "quota",
        "timeout",
        "timed out",
        "overloaded",
        "service unavailable",
        "unavailable",
        "502",
        "503",
        "504",
    )
    return any(t in s for t in tokens)


def call_with_exponential_backoff(
    fn: Callable[[], Any],
    *,
    max_retries: int = 6,
    retries: Optional[int] = None,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: float = 0.25,
    retry_after_seconds: Optional[float] = None,
    is_retryable: Optional[Callable[[Exception], bool]] = None,
    on_retry: Optional[Callable[[int, float, Exception], None]] = None,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """Executa `fn` com exponential backoff e jitter.

    Args:
        fn: Função sem argumentos.
        max_retries: Número máximo de retries, não conta a primeira tentativa.
        retries: Alias compatível com código antigo, substitui max_retries.
        base_delay: Atraso inicial em segundos.
        max_delay: Atraso máximo em segundos.
        jitter: Variação aleatória multiplicativa.
        retry_after_seconds: Mínimo a respeitar, quando a API sugere esperar.
        is_retryable: Predicado para decidir se o erro deve ter retry.
        on_retry: Callback chamado antes de dormir.
        logger: Alias compatível, se fornecido e on_retry for None, emite warning.

    Returns:
        O resultado de `fn`.

    Raises:
        Exception: Repassa a última exceção se esgotar retries.
    """
    if retries is not None:
        max_retries = int(retries)

    if on_retry is None and logger is not None:

        def _default_on_retry(attempt: int, delay: float, exc: Exception) -> None:
            logger.warning(f"Tentativa {attempt} em {delay:.1f}s, erro={exc}")

        on_retry = _default_on_retry

    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if is_retryable is not None and not is_retryable(exc):
                raise
            if attempt >= max_retries:
                raise

            delay = min(float(max_delay), float(base_delay) * (2.0**attempt))
            if float(jitter) > 0.0:
                delay *= 1.0 + random.uniform(-float(jitter), float(jitter))
            if retry_after_seconds is not None:
                delay = max(delay, float(retry_after_seconds))

            attempt += 1
            if on_retry is not None:
                on_retry(attempt, float(delay), exc)
            time.sleep(max(0.0, float(delay)))
