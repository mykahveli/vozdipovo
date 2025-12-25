#!scripts/debug_judging.py
from __future__ import annotations

import argparse
import json
import logging
import operator
import os
import socket
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from vozdipovo_app.db.migrate import ensure_schema
from vozdipovo_app.judge import evaluate_article_significance
from vozdipovo_app.settings import get_settings
from vozdipovo_app.utils.logger import get_logger

logger = get_logger("debug_judging")


def _utc_now() -> datetime:
    """Retorna agora em UTC."""
    return datetime.now(tz=timezone.utc)


def _iso(dt: datetime) -> str:
    """Formata datetime em ISO com Z."""
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_json(obj: Any, *, max_chars: int) -> str:
    """Serializa em json e limita tamanho."""
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    s = str(s).strip()
    if len(s) > int(max_chars):
        return f"{s[: int(max_chars)]}…"
    return s


def _sanitize_text(text: str) -> str:
    """Sanitiza texto para logs, substitui caracteres problemáticos."""
    s = str(text or "")
    return s.replace("`", "'").replace("\r", " ").replace("\n", " ").replace("-", "_")


def run_with_timeout(fn: Callable[[], Any], timeout_seconds: int) -> Any:
    """Executa uma função com timeout duro.

    Args:
        fn: Função.
        timeout_seconds: Timeout em segundos.

    Returns:
        Resultado.

    Raises:
        TimeoutError: Se exceder o tempo.
    """
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=max(1, int(timeout_seconds)))
        except FutureTimeout as e:
            raise TimeoutError(f"Timeout após {timeout_seconds}s") from e


def _looks_like_model_endpoint(url: str) -> bool:
    """Heurística para identificar endpoints de modelos."""
    u = str(url or "").casefold()
    needles = (
        "openai",
        "anthropic",
        "cohere",
        "mistral",
        "groq",
        "azure",
        "generativelanguage",
        "bedrock",
        "ollama",
        "v1/chat",
        "v1/responses",
        "v1/messages",
        "v1/completions",
    )
    return any(n in u for n in needles)


def _compact_prompt_from_json_payload(
    payload: Any, *, max_chars: int
) -> dict[str, Any]:
    """Extrai informação compacta de prompt, sem despejar tudo.

    Args:
        payload: Payload json.
        max_chars: Limite.

    Returns:
        Resumo.
    """
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__}

    model = payload.get("model")
    msgs = payload.get("messages")
    out: dict[str, Any] = {"model": _sanitize_text(str(model)) if model else None}

    if isinstance(msgs, list):
        out["messages_count"] = len(msgs)
        last = msgs[len(msgs) - 1] if msgs else None
        if isinstance(last, dict):
            content = last.get("content")
            content_s = _sanitize_text(str(content or ""))
            out["last_message_len"] = len(content_s)
            out["last_message_head"] = content_s[:max_chars]
    return out


class ModelHttpTrace(AbstractContextManager["ModelHttpTrace"]):
    """Trace de chamadas http para modelos, com timeout forçado."""

    def __init__(
        self,
        *,
        correlation_id: str,
        max_body_chars: int,
        force_connect_timeout: float,
        force_read_timeout: float,
    ) -> None:
        self._correlation_id = str(correlation_id)
        self._max_body_chars = int(max_body_chars)
        self._force_connect_timeout = float(force_connect_timeout)
        self._force_read_timeout = float(force_read_timeout)

        self._httpx_client_request = None
        self._httpx_async_client_request = None
        self._requests_session_request = None

    @property
    def correlation_id(self) -> str:
        """Id de correlação."""
        return self._correlation_id

    def __enter__(self) -> "ModelHttpTrace":
        self._patch_httpx()
        self._patch_requests()
        logger.info(f"trace_on,corr={self._correlation_id}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._unpatch_httpx()
        self._unpatch_requests()
        logger.info(f"trace_off,corr={self._correlation_id}")

    def _force_timeout(self, kwargs: dict[str, Any]) -> tuple[float, float]:
        timeout = kwargs.get("timeout")
        if timeout is None:
            forced = (self._force_connect_timeout, self._force_read_timeout)
            kwargs["timeout"] = forced
            return forced
        if isinstance(timeout, (int, float)):
            forced = (self._force_connect_timeout, float(timeout))
            kwargs["timeout"] = forced
            return forced
        if isinstance(timeout, tuple) and len(timeout) == 2:
            return (float(timeout[0]), float(timeout[1]))
        forced = (self._force_connect_timeout, self._force_read_timeout)
        kwargs["timeout"] = forced
        return forced

    def _patch_httpx(self) -> None:
        try:
            import httpx
        except Exception:
            return

        if self._httpx_client_request is None:
            self._httpx_client_request = httpx.Client.request

            def _client_request(
                client: Any, method: str, url: Any, **kwargs: Any
            ) -> Any:
                url_s = str(url)
                t0 = time.perf_counter()
                self._log_request("httpx", method, url_s, kwargs)
                try:
                    resp = self._httpx_client_request(client, method, url, **kwargs)
                    dt = operator.sub(time.perf_counter(), t0)
                    self._log_response("httpx", method, url_s, resp, dt)
                    return resp
                except Exception as e:
                    dt = operator.sub(time.perf_counter(), t0)
                    self._log_error("httpx", method, url_s, e, dt)
                    raise

            httpx.Client.request = _client_request

        if self._httpx_async_client_request is None:
            self._httpx_async_client_request = httpx.AsyncClient.request

            async def _async_client_request(
                client: Any, method: str, url: Any, **kwargs: Any
            ) -> Any:
                url_s = str(url)
                t0 = time.perf_counter()
                self._log_request("httpx_async", method, url_s, kwargs)
                try:
                    resp = await self._httpx_async_client_request(
                        client, method, url, **kwargs
                    )
                    dt = operator.sub(time.perf_counter(), t0)
                    self._log_response("httpx_async", method, url_s, resp, dt)
                    return resp
                except Exception as e:
                    dt = operator.sub(time.perf_counter(), t0)
                    self._log_error("httpx_async", method, url_s, e, dt)
                    raise

            httpx.AsyncClient.request = _async_client_request

    def _unpatch_httpx(self) -> None:
        try:
            import httpx
        except Exception:
            return

        if self._httpx_client_request is not None:
            httpx.Client.request = self._httpx_client_request
            self._httpx_client_request = None

        if self._httpx_async_client_request is not None:
            httpx.AsyncClient.request = self._httpx_async_client_request
            self._httpx_async_client_request = None

    def _patch_requests(self) -> None:
        try:
            import requests
        except Exception:
            return

        if self._requests_session_request is None:
            self._requests_session_request = requests.sessions.Session.request

            def _session_request(
                session: Any, method: str, url: str, **kwargs: Any
            ) -> Any:
                url_s = str(url)
                t0 = time.perf_counter()

                forced_timeout = self._force_timeout(kwargs)
                self._log_request(
                    "requests",
                    method,
                    url_s,
                    kwargs,
                    forced_timeout=forced_timeout,
                )

                try:
                    resp = self._requests_session_request(
                        session, method, url, **kwargs
                    )
                    dt = operator.sub(time.perf_counter(), t0)
                    self._log_response("requests", method, url_s, resp, dt)
                    return resp
                except Exception as e:
                    dt = operator.sub(time.perf_counter(), t0)
                    self._log_error("requests", method, url_s, e, dt)
                    raise

            requests.sessions.Session.request = _session_request

    def _unpatch_requests(self) -> None:
        try:
            import requests
        except Exception:
            return

        if self._requests_session_request is not None:
            requests.sessions.Session.request = self._requests_session_request
            self._requests_session_request = None

    def _log_request(
        self,
        lib: str,
        method: str,
        url: str,
        kwargs: dict[str, Any],
        *,
        forced_timeout: Optional[tuple[float, float]] = None,
    ) -> None:
        if not _looks_like_model_endpoint(url):
            return

        headers = (
            kwargs.get("headers") if isinstance(kwargs.get("headers"), dict) else {}
        )
        safe_headers = {
            str(k): _sanitize_text(str(v))
            for k, v in headers.items()
            if str(k).casefold()
            in ("content_type", "accept", "user_agent", "authorization")
        }
        if "authorization" in safe_headers:
            safe_headers["authorization"] = "redacted"

        json_payload = kwargs.get("json")
        json_summary = _compact_prompt_from_json_payload(
            json_payload, max_chars=min(self._max_body_chars, 400)
        )

        payload: dict[str, Any] = {
            "timeout": forced_timeout if forced_timeout else kwargs.get("timeout"),
            "headers": safe_headers,
            "json_summary": json_summary,
            "json_len": len(_safe_json(json_payload, max_chars=self._max_body_chars))
            if json_payload is not None
            else 0,
        }

        logger.info(
            _safe_json(
                {
                    "event": "model_http_request",
                    "corr": self._correlation_id,
                    "lib": lib,
                    "method": _sanitize_text(str(method)),
                    "url": _sanitize_text(str(url)),
                    "payload": payload,
                },
                max_chars=self._max_body_chars,
            )
        )

    def _log_response(
        self, lib: str, method: str, url: str, resp: Any, seconds: float
    ) -> None:
        if not _looks_like_model_endpoint(url):
            return

        status = getattr(resp, "status_code", None)
        body_text: Optional[str] = None
        try:
            if hasattr(resp, "text"):
                body_text = str(resp.text or "")
        except Exception:
            body_text = None

        body_s = _sanitize_text(body_text) if body_text else ""
        body_head = body_s[: min(self._max_body_chars, 800)] if body_s else ""

        logger.info(
            _safe_json(
                {
                    "event": "model_http_response",
                    "corr": self._correlation_id,
                    "lib": lib,
                    "method": _sanitize_text(str(method)),
                    "url": _sanitize_text(str(url)),
                    "status": status,
                    "seconds": round(float(seconds), 3),
                    "body_len": len(body_s),
                    "body_head": body_head,
                },
                max_chars=self._max_body_chars,
            )
        )

    def _log_error(
        self, lib: str, method: str, url: str, err: Exception, seconds: float
    ) -> None:
        if not _looks_like_model_endpoint(url):
            return

        logger.error(
            _safe_json(
                {
                    "event": "model_http_error",
                    "corr": self._correlation_id,
                    "lib": lib,
                    "method": _sanitize_text(str(method)),
                    "url": _sanitize_text(str(url)),
                    "seconds": round(float(seconds), 3),
                    "error_type": type(err).__name__,
                    "error": _sanitize_text(str(err)),
                },
                max_chars=self._max_body_chars,
            ),
            exc_info=True,
        )


@dataclass(frozen=True, slots=True)
class DebugConfig:
    """Config do debug.

    Attributes:
        limit: Quantos itens.
        timeout_seconds: Timeout por item.
        throttle_seconds: Espera entre itens.
        significance_threshold: Threshold.
        commit_every: Commit a cada N.
        trace_max_body_chars: Limite de logs.
        connect_timeout_seconds: Timeout de conexão.
        read_timeout_seconds: Timeout de leitura.
        socket_default_timeout_seconds: Timeout global de sockets.
    """

    limit: int
    timeout_seconds: int
    throttle_seconds: float
    significance_threshold: float
    commit_every: int
    trace_max_body_chars: int
    connect_timeout_seconds: float
    read_timeout_seconds: float
    socket_default_timeout_seconds: float


def _fetch_targets(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    q = """
    SELECT
      ld.id AS legal_doc_id,
      ld.site_name,
      COALESCE(ld.title, '') AS title,
      COALESCE(ld.url, '') AS url,
      COALESCE(ld.raw_payload_json, ld.content_text, ld.summary, ld.raw_html, '') AS snippet
    FROM legal_docs ld
    LEFT JOIN news_articles na ON na.legal_doc_id = ld.id
    WHERE na.id IS NULL
       OR na.review_status IN ('RETRY')
    ORDER BY ld.id DESC
    LIMIT ?;
    """
    return list(conn.execute(q, (int(limit),)).fetchall())


def _upsert_retry(
    conn: sqlite3.Connection,
    *,
    legal_doc_id: int,
    title: str,
    err: Exception,
    retry_after_seconds: int,
    error_kind: str,
) -> None:
    next_retry = _iso(_utc_now() + timedelta(seconds=int(retry_after_seconds)))
    conn.execute(
        """
        INSERT INTO news_articles (
          legal_doc_id,
          titulo,
          review_status,
          review_error,
          review_error_kind,
          review_http_status,
          review_attempts,
          review_next_retry_at,
          updated_at,
          created_at
        )
        VALUES (?, ?, 'RETRY', ?, ?, NULL, 1, ?, datetime('now'), datetime('now'))
        ON CONFLICT(legal_doc_id) DO UPDATE SET
          review_status='RETRY',
          review_error=excluded.review_error,
          review_error_kind=excluded.review_error_kind,
          review_attempts=COALESCE(news_articles.review_attempts, 0) + 1,
          review_next_retry_at=excluded.review_next_retry_at,
          updated_at=datetime('now');
        """,
        (
            int(legal_doc_id),
            str(title),
            _sanitize_text(str(err)),
            str(error_kind),
            str(next_retry),
        ),
    )


def _upsert_judged(
    conn: sqlite3.Connection,
    *,
    legal_doc_id: int,
    title: str,
    res: dict[str, Any],
    significance_threshold: float,
) -> None:
    final_score = float(res.get("final_score") or 0.0)
    threshold = float(significance_threshold or 0.0)
    decision = "WRITE" if final_score >= threshold else "SKIP"

    conn.execute(
        """
        INSERT INTO news_articles (
          legal_doc_id,
          titulo,
          final_score,
          score_editorial,
          judge_justification,
          reviewed_by_model,
          reviewed_at,
          decision,
          review_status,
          review_attempts,
          updated_at,
          created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'JUDGED', 1, datetime('now'), datetime('now'))
        ON CONFLICT(legal_doc_id) DO UPDATE SET
          titulo=excluded.titulo,
          final_score=excluded.final_score,
          score_editorial=excluded.score_editorial,
          judge_justification=excluded.judge_justification,
          reviewed_by_model=excluded.reviewed_by_model,
          reviewed_at=excluded.reviewed_at,
          decision=excluded.decision,
          review_status='JUDGED',
          review_error=NULL,
          review_error_kind=NULL,
          review_http_status=NULL,
          review_next_retry_at=NULL,
          updated_at=datetime('now');
        """,
        (
            int(legal_doc_id),
            str(title),
            float(final_score),
            float(res.get("score_editorial") or 0.0),
            _sanitize_text(str(res.get("judge_justification") or "")),
            _sanitize_text(str(res.get("reviewed_by_model") or "")),
            _sanitize_text(str(res.get("reviewed_at") or _iso(_utc_now()))),
            decision,
        ),
    )


def _preflight_network(host: str, port: int, timeout_seconds: float) -> dict[str, Any]:
    """Faz preflight de DNS e TCP.

    Args:
        host: Host.
        port: Porta.
        timeout_seconds: Timeout.

    Returns:
        Resultado.
    """
    out: dict[str, Any] = {"host": host, "port": port}
    try:
        t0 = time.perf_counter()
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        dt = operator.sub(time.perf_counter(), t0)
        out["dns_seconds"] = round(float(dt), 3)
        out["dns_results"] = [str(i[4]) for i in infos[:5]]
    except Exception as e:
        out["dns_error"] = _sanitize_text(str(e))
        return out

    try:
        t0 = time.perf_counter()
        s = socket.create_connection((host, port), timeout=timeout_seconds)
        s.close()
        dt = operator.sub(time.perf_counter(), t0)
        out["tcp_seconds"] = round(float(dt), 3)
        out["tcp_ok"] = True
    except Exception as e:
        out["tcp_ok"] = False
        out["tcp_error"] = _sanitize_text(str(e))

    return out


def _parse_args() -> DebugConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--throttle-seconds", type=float, default=0.0)
    parser.add_argument("--significance-threshold", type=float, default=0.0)
    parser.add_argument("--commit-every", type=int, default=1)
    parser.add_argument("--trace-max-body-chars", type=int, default=4000)
    parser.add_argument("--connect-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--read-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--socket-default-timeout-seconds", type=float, default=30.0)
    ns = parser.parse_args()

    return DebugConfig(
        limit=int(ns.limit),
        timeout_seconds=int(ns.timeout_seconds),
        throttle_seconds=float(ns.throttle_seconds),
        significance_threshold=float(ns.significance_threshold),
        commit_every=int(ns.commit_every),
        trace_max_body_chars=int(ns.trace_max_body_chars),
        connect_timeout_seconds=float(ns.connect_timeout_seconds),
        read_timeout_seconds=float(ns.read_timeout_seconds),
        socket_default_timeout_seconds=float(ns.socket_default_timeout_seconds),
    )


def main() -> int:
    logging.getLogger("urllib3").setLevel(logging.DEBUG)
    logging.getLogger("requests").setLevel(logging.DEBUG)
    socket.setdefaulttimeout(30.0)

    cfg = _parse_args()
    socket.setdefaulttimeout(float(cfg.socket_default_timeout_seconds))

    settings = get_settings()
    logger.info(f"db_path={settings.db_path}")

    env_keys = [
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    ]
    env_present = {k: bool(os.environ.get(k)) for k in env_keys}
    logger.info(
        _safe_json(
            {"event": "env_present", "env": env_present},
            max_chars=cfg.trace_max_body_chars,
        )
    )

    pre = _preflight_network(
        "api.groq.com", 443, timeout_seconds=float(cfg.connect_timeout_seconds)
    )
    logger.info(
        _safe_json(
            {"event": "preflight", "result": pre}, max_chars=cfg.trace_max_body_chars
        )
    )

    conn = ensure_schema(str(settings.db_path))
    conn.row_factory = sqlite3.Row

    try:
        rows = _fetch_targets(conn, cfg.limit)
        if not rows:
            logger.info("Sem itens para julgar")
            return 0

        processed = 0
        commit_every = max(1, int(cfg.commit_every))

        for i, r in enumerate(rows, start=1):
            legal_doc_id = int(r["legal_doc_id"])
            site_name = str(r["site_name"] or "")
            title = str(r["title"] or "")
            url = str(r["url"] or "")
            snippet = str(r["snippet"] or "")
            snippet_head = _sanitize_text(snippet[:400])

            corr = f"legal_doc_id={legal_doc_id}"

            logger.info(
                _safe_json(
                    {
                        "event": "judge_start",
                        "i": i,
                        "corr": corr,
                        "site": _sanitize_text(site_name),
                        "title_len": len(title),
                        "url_len": len(url),
                        "snippet_len": len(snippet),
                        "snippet_head": snippet_head,
                        "timeout_seconds": cfg.timeout_seconds,
                        "connect_timeout_seconds": cfg.connect_timeout_seconds,
                        "read_timeout_seconds": cfg.read_timeout_seconds,
                    },
                    max_chars=cfg.trace_max_body_chars,
                )
            )

            t0 = time.perf_counter()

            try:

                def _call() -> dict[str, Any]:
                    return evaluate_article_significance(
                        title=title,
                        text_snippet=snippet[:4000],
                        source_name=site_name,
                        url=url,
                    )

                with ModelHttpTrace(
                    correlation_id=corr,
                    max_body_chars=cfg.trace_max_body_chars,
                    force_connect_timeout=cfg.connect_timeout_seconds,
                    force_read_timeout=cfg.read_timeout_seconds,
                ):
                    res = run_with_timeout(_call, timeout_seconds=cfg.timeout_seconds)

                dt = operator.sub(time.perf_counter(), t0)

                logger.info(
                    _safe_json(
                        {
                            "event": "judge_done",
                            "corr": corr,
                            "seconds": round(float(dt), 3),
                            "final_score": res.get("final_score"),
                            "score_editorial": res.get("score_editorial"),
                            "reviewed_by_model": _sanitize_text(
                                str(res.get("reviewed_by_model") or "")
                            ),
                            "judge_justification_len": len(
                                str(res.get("judge_justification") or "")
                            ),
                        },
                        max_chars=cfg.trace_max_body_chars,
                    )
                )

                _upsert_judged(
                    conn,
                    legal_doc_id=legal_doc_id,
                    title=title,
                    res=res,
                    significance_threshold=cfg.significance_threshold,
                )
                processed += 1

            except Exception as e:
                dt = operator.sub(time.perf_counter(), t0)
                logger.error(
                    _safe_json(
                        {
                            "event": "judge_fail",
                            "corr": corr,
                            "seconds": round(float(dt), 3),
                            "error_type": type(e).__name__,
                            "error": _sanitize_text(str(e)),
                        },
                        max_chars=cfg.trace_max_body_chars,
                    ),
                    exc_info=True,
                )

                kind = "timeout" if isinstance(e, TimeoutError) else "exception"
                _upsert_retry(
                    conn,
                    legal_doc_id=legal_doc_id,
                    title=title,
                    err=e,
                    retry_after_seconds=120,
                    error_kind=kind,
                )

            if processed > 0 and (processed % commit_every) == 0:
                conn.commit()
                logger.info(f"commit,processed={processed}")

            if cfg.throttle_seconds:
                time.sleep(float(cfg.throttle_seconds))

        conn.commit()
        logger.info(
            _safe_json(
                {"event": "finished", "processed": processed},
                max_chars=cfg.trace_max_body_chars,
            )
        )
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
