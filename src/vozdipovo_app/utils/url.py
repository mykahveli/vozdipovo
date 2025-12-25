#!filepath: src/vozdipovo_app/utils/url.py
from __future__ import annotations

import re
from typing import Iterable, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_KEYS: Tuple[str, ...] = (
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
)


_TRACKING_PREFIXES: Tuple[str, ...] = (
    "utm_",
    "at_",
    "ref",
)


def canonicalize_url(url: str) -> str:
    """Canonicalize a URL for stable hashing and deduplication."""
    raw = (url or "").strip()
    if not raw:
        return ""

    try:
        p = urlparse(raw)
    except Exception:
        return raw

    scheme = (p.scheme or "https").lower()
    host = (p.hostname or "").lower()
    if not host:
        return raw

    port = p.port
    netloc = host
    if port and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    ):
        netloc = f"{host}:{port}"

    path = p.path or ""
    path = re.sub(r"/{2,}", "/", path)
    if path.endswith("/") and path != "/":
        path = path[:-1]

    pairs = []
    for k, v in parse_qsl(p.query or "", keep_blank_values=True):
        kk = (k or "").strip()
        if not kk:
            continue
        k_lower = kk.lower()
        if k_lower in _TRACKING_KEYS:
            continue
        if any(k_lower.startswith(pref) for pref in _TRACKING_PREFIXES):
            continue
        pairs.append((kk, (v or "").strip()))

    pairs.sort(key=lambda kv: (kv[0].lower(), kv[1]))
    query = urlencode(pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def canonicalize_many(urls: Iterable[str]) -> Tuple[str, ...]:
    """Canonicalize many URLs."""
    return tuple(canonicalize_url(u) for u in urls)
