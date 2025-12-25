#!filepath: src/vozdipovo_app/wordpress/client.py
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from vozdipovo_app.utils.logger import get_logger

logger = get_logger(__name__)


class WordPressError(RuntimeError):
    """Raised when WordPress integration fails."""


class WordPressRequestError(WordPressError):
    """Raised when the HTTP request fails before getting a response."""


class WordPressResponseError(WordPressError):
    """Raised when WordPress returns an invalid or error response."""


@dataclass(frozen=True, slots=True)
class WPConfig:
    """Runtime configuration for WordPress REST calls.

    Args:
        base_url: Base URL of the WordPress site.
        username: WordPress username.
        app_password: WordPress application password.
        default_status: Default post status.
        timeout: Request timeout in seconds.
        rate_sleep: Minimum seconds between requests.
    """

    base_url: str
    username: str
    app_password: str
    default_status: str = "publish"
    timeout: int = 30
    rate_sleep: float = 0.6


def _basic_auth_header(username: str, app_password: str) -> str:
    user = str(username or "").strip()
    pwd = str(app_password or "").strip()
    creds = f"{user}:{pwd}"
    token = base64.b64encode(creds.encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def _make_retry() -> Retry:
    return Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST", "PUT"),
        raise_on_status=False,
        respect_retry_after_header=True,
    )


class WPClient:
    """Low level WordPress REST client.

    This client is responsible for HTTP transport and response validation.
    """

    def __init__(self, cfg: WPConfig) -> None:
        self._cfg = cfg
        self._session = requests.Session()

        adapter = HTTPAdapter(max_retries=_make_retry())
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        self._session.headers.update(
            {
                "Authorization": _basic_auth_header(cfg.username, cfg.app_password),
                "User-Agent": "VozDiPovoBot/0.9",
            }
        )

    @property
    def cfg(self) -> WPConfig:
        """Return the configuration used by this client."""
        return self._cfg

    def _url(self, path: str) -> str:
        base = str(self._cfg.base_url).rstrip("/")
        safe_path = str(path or "").lstrip("/")
        return f"{base}/{safe_path}"

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        url = self._url(path)
        try:
            response = self._session.request(
                method=str(method).upper(),
                url=url,
                params=params,
                json=json_payload,
                headers=headers,
                data=data,
                files=files,
                timeout=float(timeout or self._cfg.timeout),
            )
        except requests.RequestException as e:
            raise WordPressRequestError(f"Falha de rede ao chamar {url}: {e}") from e

        if not 200 <= int(response.status_code) < 300:
            snippet = str(response.text or "").strip()[:800]
            raise WordPressResponseError(
                f"WordPress respondeu {response.status_code} em {url}, detalhe: {snippet}"
            )

        try:
            return response.json()
        except ValueError as e:
            snippet = str(response.text or "").strip()[:800]
            raise WordPressResponseError(
                f"Resposta WordPress sem JSON válido em {url}, detalhe: {snippet}"
            ) from e

    def get(self, path: str, **kw: Any) -> Any:
        """Perform a GET request.

        Args:
            path: Relative path.
            **kw: Forwarded to requests.

        Returns:
            Any: Parsed JSON.
        """
        params = kw.pop("params", None)
        headers = kw.pop("headers", None)
        timeout = kw.pop("timeout", None)
        return self._request_json(
            "GET", path, params=params, headers=headers, timeout=timeout
        )

    def post(self, path: str, json: Optional[Dict[str, Any]] = None, **kw: Any) -> Any:
        """Perform a POST request with a JSON payload."""
        headers = dict(kw.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/json")
        timeout = kw.pop("timeout", None)
        return self._request_json(
            "POST", path, json_payload=json, headers=headers, timeout=timeout
        )

    def put(self, path: str, json: Dict[str, Any], **kw: Any) -> Any:
        """Perform a PUT request with a JSON payload."""
        headers = dict(kw.pop("headers", {}) or {})
        headers.setdefault("Content-Type", "application/json")
        timeout = kw.pop("timeout", None)
        return self._request_json(
            "PUT", path, json_payload=json, headers=headers, timeout=timeout
        )

    def create_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a WordPress post."""
        data = self.post("/wp-json/wp/v2/posts", json=payload)
        if not isinstance(data, dict):
            raise WordPressResponseError("Resposta inesperada ao criar post")
        return data

    def update_post(self, pid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Update a WordPress post."""
        data = self.put(f"/wp-json/wp/v2/posts/{int(pid)}", json=payload)
        if not isinstance(data, dict):
            raise WordPressResponseError("Resposta inesperada ao atualizar post")
        return data

    def list_terms(self, taxonomy: str, search: Optional[str] = None) -> Any:
        """List taxonomy terms."""
        params = {"search": search} if search else None
        return self.get(f"/wp-json/wp/v2/{taxonomy}", params=params)

    def create_term(self, taxonomy: str, name: str) -> Dict[str, Any]:
        """Create a taxonomy term."""
        data = self.post(f"/wp-json/wp/v2/{taxonomy}", json={"name": name})
        if not isinstance(data, dict):
            raise WordPressResponseError("Resposta inesperada ao criar termo")
        return data

    def upload_media(
        self, file_path: str, caption: Optional[str] = None
    ) -> Optional[int]:
        """Upload a media file.

        Args:
            file_path: Local path to the media.
            caption: Optional caption.

        Returns:
            Optional[int]: Media id or None.
        """
        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.error(f"Ficheiro não existe: {file_path}")
            return None

        url_path = "/wp-json/wp/v2/media"
        data: Dict[str, Any] = {}
        if caption:
            data = {"caption": caption, "alt_text": caption, "title": caption}

        headers: Dict[str, str] = {}

        try:
            with path_obj.open("rb") as fh:
                files = {"file": (path_obj.name, fh, "application/octet-stream")}
                res = self._request_json(
                    "POST",
                    url_path,
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=max(float(self._cfg.timeout), 60.0),
                )
            if isinstance(res, dict) and res.get("id") is not None:
                return int(res["id"])
            logger.error(f"Resposta WordPress sem media id: {str(res)[:600]}")
            return None
        except WordPressError as e:
            logger.error(f"Falha upload imagem {path_obj.name}: {e}")
            return None


@lru_cache(maxsize=1)
def _default_wp_config() -> WPConfig:
    from vozdipovo_app.config import load_app_config

    cfg = load_app_config()
    wp = cfg.get("wordpress") or {}

    base_url = str(os.getenv("WP_BASE_URL", wp.get("base_url") or "")).strip()
    username = str(os.getenv("WP_USERNAME", wp.get("username") or "")).strip()
    app_password = str(
        os.getenv("WP_APP_PASSWORD", wp.get("app_password") or "")
    ).strip()

    default_status = str(wp.get("default_status") or "publish").strip().lower()
    timeout = int(wp.get("timeout") or 30)
    rate_sleep = float(wp.get("rate_sleep") or 0.6)

    if not base_url or not username or not app_password:
        raise WordPressError(
            "Config WordPress incompleto, define base_url, username e app_password, "
            "via configs ou variáveis de ambiente"
        )

    return WPConfig(
        base_url=base_url,
        username=username,
        app_password=app_password,
        default_status=default_status,
        timeout=timeout,
        rate_sleep=rate_sleep,
    )


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    """Return items deduped case insensitively while preserving order.

    Args:
        items: Iterable of raw strings.

    Returns:
        List[str]: Deduped list.
    """
    seen: set[str] = set()
    out: List[str] = []
    for item in items:
        key = str(item).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(item))
    return out


class WordPressClient:
    """High level WordPress client used by the publishing pipeline."""

    def __init__(self, cfg: Optional[WPConfig] = None) -> None:
        self._cfg = cfg or _default_wp_config()
        self._client = WPClient(self._cfg)
        self._tag_cache: Dict[str, int] = {}
        self._last_request_at = 0.0

    @property
    def cfg(self) -> WPConfig:
        """Return WordPress configuration."""
        return self._cfg

    def _throttle(self) -> None:
        minimum = float(self._cfg.rate_sleep)
        if minimum <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < minimum:
            time.sleep(minimum - elapsed)
        self._last_request_at = time.monotonic()

    def create_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._throttle()
        return self._client.create_post(payload)

    def update_post(self, pid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._throttle()
        return self._client.update_post(pid, payload)

    def upload_media(
        self, file_path: str, caption: Optional[str] = None
    ) -> Optional[int]:
        self._throttle()
        return self._client.upload_media(file_path=file_path, caption=caption)

    def ensure_tags(self, tags: Sequence[str]) -> List[int]:
        """Ensure tags exist and return their ids.

        Args:
            tags: Tag names.

        Returns:
            List[int]: WordPress tag ids.
        """
        uniq = _dedupe_preserve_order([str(t).strip() for t in tags if str(t).strip()])
        ids: List[int] = []
        for tag in uniq:
            tid = self._ensure_tag_id(tag)
            if tid is not None:
                ids.append(tid)
        return ids

    def _ensure_tag_id(self, name: str) -> Optional[int]:
        key = str(name).strip().casefold()
        if not key:
            return None
        if key in self._tag_cache:
            return self._tag_cache[key]

        from vozdipovo_app.wordpress.taxonomies import get_or_create_term

        self._throttle()
        term = get_or_create_term(self._client, "tags", str(name).strip())
        if term is None:
            logger.warning(f"Falha ao resolver tag: {name}")
            return None
        self._tag_cache[key] = int(term.id)
        return int(term.id)
