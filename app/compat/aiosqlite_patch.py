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
from functools import partial
from typing import Any


def apply_aiosqlite_future_poll_patch() -> None:
    """Patch aiosqlite internals to avoid Python 3.12 Future wake-up hangs."""
    try:
        from aiosqlite.core import Connection
    except Exception:
        return

    if getattr(Connection, "_marketmind_future_poll_patch", False):
        return

    async def _await_future_poll(future: asyncio.Future | None) -> Any:
        while future is not None and not future.done():
            await asyncio.sleep(0.001)
        return future.result() if future is not None else None

    async def _connect(self):
        if self._connection is None:
            try:
                future = asyncio.get_event_loop().create_future()
                self._tx.put_nowait((future, self._connector))
                self._connection = await _await_future_poll(future)
            except BaseException:
                self.stop()
                self._connection = None
                raise
        return self

    async def _execute(self, fn, *args, **kwargs):
        if not self._running or not self._connection:
            raise ValueError("Connection closed")

        future = asyncio.get_event_loop().create_future()
        self._tx.put_nowait((future, partial(fn, *args, **kwargs)))
        return await _await_future_poll(future)

    async def close(self) -> None:
        if self._connection is None:
            return
        try:
            await self._execute(self._conn.close)
        finally:
            self._connection = None
            await _await_future_poll(self.stop())

    Connection._connect = _connect
    Connection._execute = _execute
    Connection.close = close
    Connection._marketmind_future_poll_patch = True
