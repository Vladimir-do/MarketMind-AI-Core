"""Stateless helpers used by Database's telemetry methods (app/database/core.py)."""

import hashlib
import json
import os
from pathlib import Path

from app.config import BLOCK_PATTERNS_JSONL, SCRAPE_ATTEMPTS_JSONL


def url_to_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _scrape_attempts_jsonl_path() -> Path | None:
    raw = os.getenv("SCRAPE_ATTEMPTS_JSONL", "").strip()
    if not raw:
        return SCRAPE_ATTEMPTS_JSONL
    return Path(raw)


def _block_patterns_jsonl_path() -> Path | None:
    raw = os.getenv("BLOCK_PATTERNS_JSONL", "").strip()
    if not raw:
        return BLOCK_PATTERNS_JSONL
    return Path(raw)


def _site_from_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    return (urlparse(url).netloc or "").lower() or None


def _text_payload(value: str | list[str] | tuple[str, ...] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value[:1000] if value else None
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        return None
    return json.dumps(items, ensure_ascii=False)[:1000]
