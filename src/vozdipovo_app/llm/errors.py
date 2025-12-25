#!src/vozdipovo_app/llm/errors.py
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


def _dash() -> str:
    return chr(45)


class ErrorKind(str, Enum):
    UNKNOWN = "unknown"
    NETWORK = "network"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PARSE = "parse"
    SERVER_ERROR = "server_error"
    ALL_MODELS_UNAVAILABLE = "all_models_unavailable"


@dataclass(frozen=True, slots=True)
class LLMErrorDetails:
    kind: ErrorKind
    provider: Optional[str] = None
    model: Optional[str] = None
    status_code: Optional[int] = None
    retry_after_seconds: Optional[int] = None
    message: str = ""
    raw: Optional[str] = None
    extra: Optional[dict[str, Any]] = None

    @property
    def reason(self) -> str:
        return str(self.kind.value)

    @property
    def http_status(self) -> Optional[int]:
        return self.status_code


class LLMError(Exception):
    def __init__(self, payload: str | LLMErrorDetails) -> None:
        if isinstance(payload, LLMErrorDetails):
            msg = str(payload.message or payload.reason or "llm_error")
            super().__init__(msg)
            self._details = payload
        else:
            super().__init__(str(payload or "llm_error"))
            self._details = LLMErrorDetails(
                kind=ErrorKind.UNKNOWN, message=str(payload or "")
            )

    @property
    def details(self) -> LLMErrorDetails:
        return self._details

    @property
    def provider(self) -> Optional[str]:
        return self._details.provider

    @property
    def model(self) -> Optional[str]:
        return self._details.model

    @property
    def http_status(self) -> Optional[int]:
        return self._details.status_code

    @property
    def reason(self) -> str:
        return self._details.reason

    @property
    def retryable(self) -> bool:
        return self._details.kind in {
            ErrorKind.NETWORK,
            ErrorKind.TIMEOUT,
            ErrorKind.RATE_LIMIT,
            ErrorKind.PROVIDER_UNAVAILABLE,
            ErrorKind.SERVER_ERROR,
        }

    @property
    def cooldown_seconds(self) -> int:
        if self._details.retry_after_seconds is not None:
            return int(max(0, self._details.retry_after_seconds))
        if self._details.kind == ErrorKind.RATE_LIMIT:
            return 600
        if self._details.kind in {ErrorKind.TIMEOUT, ErrorKind.NETWORK}:
            return 90
        if self._details.kind in {
            ErrorKind.PROVIDER_UNAVAILABLE,
            ErrorKind.SERVER_ERROR,
        }:
            return 120
        return 0


class LLMRetryableError(LLMError):
    pass


class LLMNonRetryableError(LLMError):
    pass


class AllModelsUnavailableError(LLMError):
    def __init__(
        self,
        *,
        tried_models: Optional[Sequence[str]] = None,
        last_error: Optional[BaseException] = None,
        provider: Optional[str] = None,
    ) -> None:
        tried = list(tried_models or [])
        extra: dict[str, Any] = {"tried_models": tried}
        if last_error is not None:
            extra["last_error_type"] = type(last_error).__name__
            extra["last_error_message"] = str(last_error)

        details = LLMErrorDetails(
            kind=ErrorKind.ALL_MODELS_UNAVAILABLE,
            provider=provider,
            message="all models unavailable",
            extra=extra,
        )
        super().__init__(details)
        self._tried_models = tried
        self._last_error = last_error

    @property
    def tried_models(self) -> list[str]:
        return list(self._tried_models)

    @property
    def last_error(self) -> Optional[BaseException]:
        return self._last_error


@dataclass(frozen=True, slots=True)
class LLMErrorClassification:
    retryable: bool
    cooldown_seconds: int = 0
    reason: str = ""
    http_status: Optional[int] = None


RetryClass = LLMErrorClassification


def _build_header(name: str) -> str:
    return name.replace("_", _dash())


def parse_retry_after_seconds(headers: Mapping[str, str]) -> Optional[int]:
    key = _build_header("Retry_After")
    v = (headers.get(key) or headers.get(key.lower()) or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except Exception:
        return None


def parse_ratelimit_reset_epoch_seconds(headers: Mapping[str, str]) -> Optional[int]:
    k1 = _build_header("X_RateLimit_Reset")
    k2 = _build_header("RateLimit_Reset")
    for k in (k1, k1.lower(), k2, k2.lower()):
        v = (headers.get(k) or "").strip()
        if not v:
            continue
        try:
            return int(float(v))
        except Exception:
            continue
    return None


_status_re = re.compile(r"\b([12345]\d\d)\b")


def _extract_http_status(message: str) -> Optional[int]:
    m = _status_re.search(message or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def classify_llm_error(e: BaseException) -> LLMErrorClassification:
    msg = str(e) or ""
    low = msg.lower()
    http_status = _extract_http_status(msg)

    if isinstance(e, LLMError):
        return LLMErrorClassification(
            retryable=bool(e.retryable),
            cooldown_seconds=int(e.cooldown_seconds),
            reason=str(e.reason or ""),
            http_status=e.http_status,
        )

    if isinstance(e, TimeoutError) or "timeout" in low or "timed out" in low:
        return LLMErrorClassification(True, 90, ErrorKind.TIMEOUT.value, http_status)

    if (
        http_status == 429
        or "rate limit" in low
        or "too many requests" in low
        or "rate_limit" in low
    ):
        return LLMErrorClassification(True, 600, ErrorKind.RATE_LIMIT.value, 429)

    if http_status in {401, 403} or "unauthorized" in low or "forbidden" in low:
        return LLMErrorClassification(False, 0, ErrorKind.AUTH.value, http_status)

    if http_status == 404 or "not found" in low:
        return LLMErrorClassification(False, 0, ErrorKind.NOT_FOUND.value, 404)

    if http_status in {400, 422} or "bad request" in low or "invalid" in low:
        return LLMErrorClassification(
            False, 0, ErrorKind.INVALID_REQUEST.value, http_status
        )

    if http_status is not None and 500 <= http_status <= 599:
        return LLMErrorClassification(
            True, 120, ErrorKind.SERVER_ERROR.value, http_status
        )

    if "overloaded" in low or "service unavailable" in low or "unavailable" in low:
        return LLMErrorClassification(
            True, 120, ErrorKind.PROVIDER_UNAVAILABLE.value, http_status
        )

    return LLMErrorClassification(False, 0, ErrorKind.UNKNOWN.value, http_status)


def decide_retry(e: BaseException) -> LLMErrorClassification:
    return classify_llm_error(e)


def now_epoch_seconds() -> int:
    return int(time.time())


__all__ = [
    "ErrorKind",
    "LLMErrorDetails",
    "LLMError",
    "LLMRetryableError",
    "LLMNonRetryableError",
    "AllModelsUnavailableError",
    "LLMErrorClassification",
    "RetryClass",
    "parse_retry_after_seconds",
    "parse_ratelimit_reset_epoch_seconds",
    "classify_llm_error",
    "decide_retry",
    "now_epoch_seconds",
]
