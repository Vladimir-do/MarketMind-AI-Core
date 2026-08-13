"""Compatibility patch for aiosqlite on affected Python 3.12 runtimes.

Some Python 3.12 builds can fail to resume tasks waiting on Future objects
completed after sqlite3 work in a background thread. aiosqlite depends on that
thread-to-loop wake-up path, so DB initialization can hang forever.

The patch keeps aiosqlite's public API intact and only changes internal awaits
to poll the queued Future with a tiny sleep. It is intentionally idempotent and
safe to import before SQLAlchemy creates the SQLite async engine.
"""

from __future__ import annotations

import asyncio
import contextlib
from functools import partial
from typing import Any

# aiosqlite version this patch's private-attribute access (_tx, _connector,
# _conn, _running, stop()) was last verified against. Bump this after
# re-checking the patch against a newer aiosqlite release.
_VALIDATED_AIOSQLITE_VERSION = "0.22.1"


def _patch_incompatible(exc: AttributeError, installed_version: str) -> RuntimeError:
    return RuntimeError(
        "app/compat/aiosqlite_patch.py is incompatible with the installed "
        f"aiosqlite {installed_version} (internals it relies on were last "
        f"verified against aiosqlite {_VALIDATED_AIOSQLITE_VERSION}): {exc}. "
        "Update or remove this compatibility patch for the installed version."
    )


def apply_aiosqlite_future_poll_patch() -> None:
    """Patch aiosqlite internals to avoid Python 3.12 Future wake-up hangs."""
    try:
        import aiosqlite
        from aiosqlite.core import Connection
    except Exception:
        return

    if getattr(Connection, "_marketmind_future_poll_patch", False):
        return

    installed_version = getattr(aiosqlite, "__version__", "unknown")
    if installed_version != _VALIDATED_AIOSQLITE_VERSION:
        from app.config import logger
        logger.warning(
            "aiosqlite %s is installed, but app/compat/aiosqlite_patch.py "
            "was last verified against %s. If DB startup hangs or raises "
            "AttributeError from aiosqlite internals, this patch needs "
            "updating for the new version.",
            installed_version, _VALIDATED_AIOSQLITE_VERSION,
        )

    async def _await_future_poll(future: asyncio.Future | None) -> Any:
        while future is not None and not future.done():
            await asyncio.sleep(0.001)
        return future.result() if future is not None else None

    async def _connect(self):
        if self._connection is None:
            try:
                future = asyncio.get_running_loop().create_future()
                self._tx.put_nowait((future, self._connector))
                self._connection = await _await_future_poll(future)
            except AttributeError as exc:
                with contextlib.suppress(Exception):
                    self.stop()
                self._connection = None
                raise _patch_incompatible(exc, installed_version) from exc
            except BaseException:
                self.stop()
                self._connection = None
                raise
        return self

    async def _execute(self, fn, *args, **kwargs):
        if not self._running or not self._connection:
            raise ValueError("Connection closed")

        try:
            future = asyncio.get_running_loop().create_future()
            self._tx.put_nowait((future, partial(fn, *args, **kwargs)))
            return await _await_future_poll(future)
        except AttributeError as exc:
            raise _patch_incompatible(exc, installed_version) from exc

    async def close(self) -> None:
        if self._connection is None:
            return
        try:
            await self._execute(self._conn.close)
        except AttributeError as exc:
            raise _patch_incompatible(exc, installed_version) from exc
        finally:
            self._connection = None
            await _await_future_poll(self.stop())

    Connection._connect = _connect
    Connection._execute = _execute
    Connection.close = close
    Connection._marketmind_future_poll_patch = True
