"""Pure adaptive cooldown / circuit-breaker scoring helpers.

Used by Database.get_marketplace_health() / recommend_scrape_strategy() /
record_scrape_attempt() (app/database/core.py) to turn raw scrape telemetry
into strategy recommendations. No ORM/session access here -- these functions
only take/return plain values.
"""

import os


def _next_best_strategy_for(source: str, status: str) -> str:
    if status == "ok":
        return "reuse_current_strategy"
    if source == "browser":
        return "api_or_structured_source_only"
    if source in {"api", "html"}:
        return "try_structured_source_then_browser_if_allowed"
    if source == "search":
        return "try_direct_product_url_or_api"
    if source == "strategy":
        return "wait_for_cooldown_or_change_route"
    return "try_fallback_strategy"


def _is_network_failure(error_class: str | None, error_text: str | None) -> bool:
    text = f"{error_class or ''} {error_text or ''}".lower()
    return any(
        marker in text
        for marker in (
            "winerror 64",
            "connection reset",
            "connectionreseterror",
            "server disconnected",
            "timeout",
            "proxy",
            "cannot connect",
            "connection refused",
            "dns",
        )
    )


def _classify_failure_trigger(
    *,
    status: str,
    http_status: int | None,
    error_class: str | None,
    error_text: str | None,
) -> str | None:
    text = (error_text or "").lower()
    if "abt-challenge" in text:
        return "abt-challenge"
    if "fab_chlg" in text:
        return "fab_chlg"
    if "fab_nmk" in text:
        return "fab_nmk"
    if "captcha" in text:
        return "captcha"
    if http_status in {403, 429}:
        return f"http_{http_status}"
    if status == "blocked":
        return "blocked"
    if _is_network_failure(error_class, error_text):
        return "network"
    return None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _adaptive_cooldown(block_count: int) -> int:
    if block_count <= 0:
        return 0
    raw = os.getenv("ADAPTIVE_COOLDOWN_STEPS", "1:300,2:1800,3:7200").strip()
    steps: list[tuple[int, int]] = []
    for item in raw.split(","):
        if ":" not in item:
            continue
        left, right = item.split(":", 1)
        try:
            steps.append((int(left.strip()), int(right.strip())))
        except ValueError:
            continue
    if not steps:
        steps = [(1, 300), (2, 1800), (3, 7200)]
    steps.sort()
    cooldown = steps[0][1]
    for threshold, seconds in steps:
        if block_count >= threshold:
            cooldown = seconds
    if block_count > steps[-1][0]:
        extra = block_count - steps[-1][0]
        cooldown *= 2 ** min(extra, 4)
    return min(cooldown, _env_int("ADAPTIVE_MAX_COOLDOWN_SEC", 21600))


def _success_rate(total: int, ok: int) -> float:
    if total <= 0:
        return 0.0
    return round(ok / total, 4)


def _score_source(*, success_rate: float, block_rate: float, heat_score: float, bias: float = 0.0) -> float:
    score = (success_rate * 0.65) + ((1.0 - block_rate) * 0.25) + bias - (heat_score * 0.2)
    return round(max(0.0, min(1.0, score)), 4)
