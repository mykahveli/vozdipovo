#!src/vozdipovo_app/llm/http_transport.py
from __future__ import annotations

import json
import operator
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping

import requests
from requests import Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from vozdipovo_app.llm.errors import (
    ErrorKind,
    LLMError,
    LLMErrorDetails,
    parse_ratelimit_reset_epoch_seconds,
    parse_retry_after_seconds,
)


@dataclass(frozen=True, slots=True)
class HTTPTransport:
    """Transporte HTTP partilhado com retries e timeouts.

    Args:
        timeout_seconds: Timeout total por request em segundos.
    """

    timeout_seconds: int

    def session(self) -> requests.Session:
        """Cria uma sessão requests com retries seguros.

        Returns:
            Sessão configurada.
        """
        s = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("POST",),
            raise_on_status=False,
        )
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        return s

    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Dict[str, Any],
        provider: str,
        model: str,
    ) -> Dict[str, Any]:
        """POST json com limite total de tempo e mapeamento robusto de erros.

        Args:
            url: Endpoint.
            headers: Headers.
            payload: Payload.
            provider: Provider.
            model: Modelo.

        Returns:
            Resposta json.

        Raises:
            LLMError: Erro normalizado.
        """
        total_timeout = int(max(1, int(self.timeout_seconds)))
        connect_timeout = int(max(1, min(10, total_timeout)))
        read_timeout = int(max(1, min(30, total_timeout)))

        s = self.session()
        t0 = time.perf_counter()

        try:
            r = s.post(
                url,
                headers=dict(headers),
                json=payload,
                timeout=(connect_timeout, read_timeout),
                stream=True,
            )
        except requests.Timeout as ex:
            raise LLMError(
                LLMErrorDetails(
                    kind=ErrorKind.TIMEOUT,
                    provider=provider,
                    model=model,
                    message=str(ex),
                )
            ) from ex
        except requests.RequestException as ex:
            raise LLMError(
                LLMErrorDetails(
                    kind=ErrorKind.NETWORK,
                    provider=provider,
                    model=model,
                    message=str(ex),
                )
            ) from ex

        try:
            body = self._read_with_total_timeout(
                r=r,
                started_at=t0,
                total_timeout_seconds=total_timeout,
                provider=provider,
                model=model,
            )
            return self._handle_response_text(
                r=r, body_text=body, provider=provider, model=model
            )
        finally:
            try:
                r.close()
            except Exception:
                pass

    def _read_with_total_timeout(
        self,
        r: Response,
        started_at: float,
        total_timeout_seconds: int,
        provider: str,
        model: str,
    ) -> str:
        max_bytes = 2_000_000
        chunks: list[bytes] = []

        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)

            elapsed = operator.sub(time.perf_counter(), started_at)
            if float(elapsed) > float(total_timeout_seconds):
                try:
                    r.close()
                except Exception:
                    pass
                raise LLMError(
                    LLMErrorDetails(
                        kind=ErrorKind.TIMEOUT,
                        provider=provider,
                        model=model,
                        status_code=int(getattr(r, "status_code", 0) or 0) or None,
                        message=f"Timeout total excedido: {total_timeout_seconds}s",
                    )
                )

            current_size = sum(len(c) for c in chunks)
            if int(current_size) > int(max_bytes):
                try:
                    r.close()
                except Exception:
                    pass
                raise LLMError(
                    LLMErrorDetails(
                        kind=ErrorKind.INVALID_REQUEST,
                        provider=provider,
                        model=model,
                        status_code=int(getattr(r, "status_code", 0) or 0) or None,
                        message=f"Resposta demasiado grande, bytes={current_size}",
                    )
                )

        data = b"".join(chunks)
        return data.decode("utf8", errors="replace")

    def _handle_response_text(
        self, r: Response, body_text: str, provider: str, model: str
    ) -> Dict[str, Any]:
        status = int(r.status_code)
        headers = r.headers

        if 200 <= status < 300:
            try:
                parsed = json.loads(body_text)
                if isinstance(parsed, dict):
                    return dict(parsed)
                raise ValueError("JSON não é um objeto")
            except Exception as ex:
                raise LLMError(
                    LLMErrorDetails(
                        kind=ErrorKind.PARSE,
                        provider=provider,
                        model=model,
                        status_code=status,
                        message=str(ex),
                        raw=str(body_text or "")[:2000],
                    )
                ) from ex

        retry_after = parse_retry_after_seconds(headers) or 0
        reset_epoch = parse_ratelimit_reset_epoch_seconds(headers)
        if status == 429 and reset_epoch:
            now = int(time.time())
            retry_after = int(max(retry_after, reset_epoch - now))

        kind = self._kind_from_status(status)
        raw_text = str(body_text or "")[:2000]
        msg = self._best_message(raw_text)

        raise LLMError(
            LLMErrorDetails(
                kind=kind,
                provider=provider,
                model=model,
                status_code=status,
                retry_after_seconds=int(retry_after) if retry_after > 0 else None,
                message=msg,
                raw=raw_text,
                meta={"url": str(r.url)},
            )
        )

    def _kind_from_status(self, status: int) -> ErrorKind:
        if status == 401 or status == 403:
            return ErrorKind.AUTH
        if status == 404:
            return ErrorKind.NOT_FOUND
        if status == 429:
            return ErrorKind.RATE_LIMIT
        if status == 400 or status == 422:
            return ErrorKind.INVALID_REQUEST
        if 500 <= status < 600:
            return ErrorKind.PROVIDER_UNAVAILABLE
        return ErrorKind.UNKNOWN

    def _best_message(self, body: str) -> str:
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    m = str(err.get("message") or "").strip()
                    return m if m else body
        except Exception:
            pass
        return body


if __name__ == "__main__":
    t = HTTPTransport(timeout_seconds=3)
    print(t.timeout_seconds)
