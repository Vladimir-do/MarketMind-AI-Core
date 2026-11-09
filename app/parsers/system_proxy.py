"""Opt-in, serialized system-proxy bypass for Ozon browser sessions.

Changing the desktop proxy affects every application in the logged-in session.
It is disabled by default. When explicitly enabled, a process-wide lock keeps
concurrent MarketMind processes from racing, and a small recovery marker lets
the next run restore the original mode after an unclean process exit.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from app.config import logger

_PROXY_SCHEMA = "org.gnome.system.proxy"
_lock = asyncio.Lock()
_LOCK_PATH = Path(tempfile.gettempdir()) / "marketmind-system-proxy.lock"
_STATE_PATH = Path(tempfile.gettempdir()) / "marketmind-system-proxy-state.json"


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
    except Exception as exc:
        logger.warning("gsettings get proxy mode failed: %s", exc)
        return None
    if result.returncode != 0:
        logger.warning("gsettings get proxy mode failed with exit code %s", result.returncode)
        return None
    return result.stdout.strip().strip("'")


def _set_mode(mode: str) -> bool:
    try:
        result = subprocess.run(
            ["gsettings", "set", _PROXY_SCHEMA, "mode", mode],
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        logger.warning("gsettings set proxy mode failed: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning("gsettings set proxy mode failed with exit code %s", result.returncode)
        return False
    return True


def _acquire_process_lock():
    """Acquire an OS-level lock; return its open handle for the whole session."""
    handle = _LOCK_PATH.open("a+b")
    deadline = time.monotonic() + 30
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if handle.read(1) == b"":
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except (BlockingIOError, OSError):
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError("Timed out waiting for the system-proxy lock") from None
            time.sleep(0.1)


def _release_process_lock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _read_recovery_mode() -> str | None:
    try:
        payload = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("Не удалось прочитать маркер восстановления системного прокси") from exc
    mode = payload.get("original_mode") if isinstance(payload, dict) else None
    if not isinstance(mode, str) or not mode or mode == "none":
        raise RuntimeError("Маркер восстановления системного прокси повреждён")
    return mode


def _write_recovery_mode(mode: str) -> None:
    temp_path = _STATE_PATH.with_suffix(f".tmp-{os.getpid()}")
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"original_mode": mode}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, _STATE_PATH)
    finally:
        with suppress(FileNotFoundError):
            temp_path.unlink()


def _restore_stale_proxy_state() -> None:
    original = _read_recovery_mode()
    if original is None:
        return
    current = _get_mode()
    if current is None:
        raise RuntimeError("Не удалось проверить системный прокси перед восстановлением")
    if current != original and not _set_mode(original):
        raise RuntimeError("Не удалось восстановить системный прокси после предыдущего аварийного завершения")
    _STATE_PATH.unlink(missing_ok=True)
    logger.warning("Ozon: восстановлен системный прокси после незавершённого предыдущего запуска")


@asynccontextmanager
async def bypass_system_proxy():
    """Recover stale state unconditionally; bypass only with explicit opt-in."""
    enabled = os.getenv("MARKETMIND_BYPASS_SYSTEM_PROXY", "").strip() == "1"
    recovery_pending = _STATE_PATH.exists()
    if not enabled and not recovery_pending:
        yield
        return
    if not _gsettings_available():
        yield
        return

    async with _lock:
        process_lock = await asyncio.to_thread(_acquire_process_lock)
        try:
            await asyncio.to_thread(_restore_stale_proxy_state)
            if not enabled:
                yield
                return
            original = await asyncio.to_thread(_get_mode)
            if original is None:
                raise RuntimeError("Не удалось определить текущий режим системного прокси")
            should_restore = original != "none"
            if should_restore:
                await asyncio.to_thread(_write_recovery_mode, original)
                if not await asyncio.to_thread(_set_mode, "none"):
                    restored = await asyncio.to_thread(_set_mode, original)
                    if restored:
                        _STATE_PATH.unlink(missing_ok=True)
                    raise RuntimeError("Не удалось отключить системный прокси для Ozon")
            try:
                yield
            finally:
                if should_restore:
                    if await asyncio.to_thread(_set_mode, original):
                        _STATE_PATH.unlink(missing_ok=True)
                        logger.info("Ozon: системный прокси восстановлен")
                    else:
                        logger.error(
                            "Ozon: НЕ УДАЛОСЬ восстановить системный прокси; "
                            "маркер сохранён для восстановления при следующем запуске"
                        )
        finally:
            await asyncio.to_thread(_release_process_lock, process_lock)
