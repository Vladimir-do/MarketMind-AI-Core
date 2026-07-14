import asyncio
import random
import time
from dataclasses import dataclass

from app.config import (
    CIRCUIT_BLOCK_THRESHOLD,
    COOLDOWN_STEPS_MINUTES,
    RATE_LIMIT_OZON_MAX_SEC,
    RATE_LIMIT_OZON_MIN_SEC,
    RATE_LIMIT_WB_MAX_SEC,
    RATE_LIMIT_WB_MIN_SEC,
)


@dataclass
class _State:
    next_allowed_at: float = 0.0
    consecutive_blocks: int = 0
    open_until: float = 0.0
    last_alert_open_until: float = 0.0


class MarketplaceResilience:
    def __init__(self) -> None:
        self._states: dict[str, _State] = {
            "ozon": _State(),
            "wildberries": _State(),
        }

    def _rate_window(self, marketplace: str) -> tuple[float, float]:
        if marketplace == "ozon":
            return RATE_LIMIT_OZON_MIN_SEC, RATE_LIMIT_OZON_MAX_SEC
        return RATE_LIMIT_WB_MIN_SEC, RATE_LIMIT_WB_MAX_SEC

    async def wait_rate_limit(self, marketplace: str) -> None:
        state = self._states.setdefault(marketplace, _State())
        now = time.monotonic()
        wait = state.next_allowed_at - now
        if wait > 0:
            await asyncio.sleep(wait)
        lo, hi = self._rate_window(marketplace)
        state.next_allowed_at = time.monotonic() + random.uniform(max(0.1, lo), max(lo, hi))

    def cooldown_remaining(self, marketplace: str) -> int:
        state = self._states.setdefault(marketplace, _State())
        return max(0, int(state.open_until - time.monotonic()))

    def is_open(self, marketplace: str) -> bool:
        return self.cooldown_remaining(marketplace) > 0

    def mark_success(self, marketplace: str) -> None:
        state = self._states.setdefault(marketplace, _State())
        state.consecutive_blocks = 0
        state.open_until = 0.0
        state.last_alert_open_until = 0.0

    def mark_block(self, marketplace: str) -> int:
        state = self._states.setdefault(marketplace, _State())
        state.consecutive_blocks += 1
        if state.consecutive_blocks < CIRCUIT_BLOCK_THRESHOLD:
            return 0
        idx = min(
            state.consecutive_blocks - CIRCUIT_BLOCK_THRESHOLD,
            len(COOLDOWN_STEPS_MINUTES) - 1,
        )
        cooldown_sec = COOLDOWN_STEPS_MINUTES[idx] * 60
        state.open_until = time.monotonic() + cooldown_sec
        return cooldown_sec

    def should_emit_open_alert(self, marketplace: str) -> bool:
        state = self._states.setdefault(marketplace, _State())
        if state.open_until <= 0:
            return False
        if state.last_alert_open_until >= state.open_until:
            return False
        state.last_alert_open_until = state.open_until
        return True


resilience = MarketplaceResilience()
