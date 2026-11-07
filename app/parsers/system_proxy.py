"""
system_proxy.py — временный обход системного прокси (gsettings) для Ozon.

На машине разработчика системный HTTP/HTTPS-прокси (org.gnome.system.proxy)
указывает на локальный VPN-клиент (Happ), который заворачивает трафик через
датацентровый IP. Ozon блокирует такие IP на уровне антибота ещё до проверки
браузерного фингерпринта. Chromium (и, следовательно, Playwright) на Linux
читает этот системный прокси напрямую, независимо от --no-proxy-server и
proxy={"server": "direct://"} — единственный надёжный обход — временно
выключить сам gsettings-прокси на время работы с Ozon.

Если gsettings недоступен (не GNOME/MATE-окружение, другая ОС, CI) — просто
не делает ничего, чтобы не ломать код на других машинах.
"""

import asyncio
import shutil
import subprocess
from contextlib import asynccontextmanager

from app.config import logger

_PROXY_SCHEMA = "org.gnome.system.proxy"
_lock = asyncio.Lock()


def _gsettings_available() -> bool:
    return shutil.which("gsettings") is not None


def _get_mode() -> str | None:
    try:
        result = subprocess.run(
            ["gsettings", "get", _PROXY_SCHEMA, "mode"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().strip("'")


def _set_mode(mode: str) -> None:
    try:
        subprocess.run(
            ["gsettings", "set", _PROXY_SCHEMA, "mode", mode],
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        logger.debug(f"gsettings set proxy mode failed: {exc}")


@asynccontextmanager
async def bypass_system_proxy():
    """Временно выключает системный прокси на время работы блока кода."""
    if not _gsettings_available():
        yield
        return

    async with _lock:
        original = _get_mode()
        should_restore = bool(original) and original != "none"
        if should_restore:
            logger.info(f"Ozon: временно отключаю системный прокси (было: {original})")
            _set_mode("none")
        try:
            yield
        finally:
            if should_restore:
                _set_mode(original)
                logger.info("Ozon: системный прокси восстановлен")
