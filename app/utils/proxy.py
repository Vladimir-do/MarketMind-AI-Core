from __future__ import annotations

import socket
from urllib.parse import urlparse


def mask_proxy_url(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return "не задан"
    parsed = urlparse(value)
    if not parsed.scheme:
        return "***"
    host = parsed.hostname or "unknown-host"
    port = f":{parsed.port}" if parsed.port else ""
    if parsed.username or parsed.password:
        return f"{parsed.scheme}://***@{host}{port}"
    return f"{parsed.scheme}://{host}{port}"


def proxy_is_reachable(proxy_url: str, timeout_s: float = 0.8) -> bool:
    """
    Быстрая проверка: можем ли мы подключиться к host:port прокси.
    Это НЕ проверяет “интернет через прокси”, только то что порт слушает.
    """
    try:
        p = urlparse(proxy_url)
        host = p.hostname
        port = p.port
        if not host or not port:
            return False
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except Exception:
        return False

