import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Обязательная переменная {key} не задана в .env")
    return val


def _normalize_proxy(value: str | None) -> str:
    proxy = (value or "").strip()
    if not proxy:
        return ""

    parsed = urlparse(proxy)
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    if host.lower() in {"ip", "host", "example.com", "proxy.example.com"} or not port:
        return ""

    return proxy


def _first_proxy_env(*keys: str) -> str:
    for key in keys:
        proxy = _normalize_proxy(os.getenv(key, ""))
        if proxy:
            return proxy
    return ""


# ── Telegram ──────────────────────────────────────────────────────────────────
def _env_bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]
TELEGRAM_DROP_PENDING_UPDATES: bool = _env_bool("TELEGRAM_DROP_PENDING_UPDATES", "0")


def require_bot_token() -> str:
    return _require("BOT_TOKEN")

# ── Claude AI ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")  # legacy
GROK_API_KEY: str = os.getenv("GROK_API_KEY", "")
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "grok")  # grok / claude

# ── База данных ───────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///app/data/parser.db")
if DATABASE_URL.startswith("sqlite+aiosqlite:///"):
    _db_path = Path(DATABASE_URL.removeprefix("sqlite+aiosqlite:///"))
    if not _db_path.is_absolute():
        _db_path = _PROJECT_ROOT / _db_path
        DATABASE_URL = f"sqlite+aiosqlite:///{_db_path.as_posix()}"
    if _db_path.suffix == ".db":
        _db_path.parent.mkdir(parents=True, exist_ok=True)

# ── Прокси ────────────────────────────────────────────────────────────────────
COMMON_PROXY: str = _normalize_proxy(os.getenv("COMMON_PROXY", ""))
PARSER_PROXY: str = _normalize_proxy(os.getenv("PARSER_PROXY", "")) or _normalize_proxy(os.getenv("PROXY", "")) or COMMON_PROXY
TELEGRAM_PROXY: str = (
    _normalize_proxy(os.getenv("TELEGRAM_API_PROXY", ""))
    or _normalize_proxy(os.getenv("TELEGRAM_PROXY", ""))
    or COMMON_PROXY
)

# Backward-compatible aliases used by parser/worker modules.
PROXY: str = PARSER_PROXY
PROXY_URL: str = PROXY
PROXIES: dict[str, str] = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else {}

# ── Парсинг ───────────────────────────────────────────────────────────────────
DELAY_MIN: float = float(os.getenv("DELAY_MIN", "3"))
DELAY_MAX: float = float(os.getenv("DELAY_MAX", "7"))
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
RETRY_ATTEMPTS: int = int(os.getenv("RETRY_ATTEMPTS", "3"))
WB_CLOUD_FUNCTION_URL: str = os.getenv("WB_CLOUD_FUNCTION_URL", "").strip()
WB_CLOUD_FIRST: bool = os.getenv("WB_CLOUD_FIRST", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WB_CLOUD_FALLBACK_LOCAL: bool = os.getenv("WB_CLOUD_FALLBACK_LOCAL", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Resilience / anti-block control plane
RATE_LIMIT_WB_MIN_SEC: float = float(os.getenv("RATE_LIMIT_WB_MIN_SEC", "1.5"))
RATE_LIMIT_WB_MAX_SEC: float = float(os.getenv("RATE_LIMIT_WB_MAX_SEC", "3.5"))
RATE_LIMIT_OZON_MIN_SEC: float = float(os.getenv("RATE_LIMIT_OZON_MIN_SEC", "5.2"))
RATE_LIMIT_OZON_MAX_SEC: float = float(os.getenv("RATE_LIMIT_OZON_MAX_SEC", "12.8"))
CIRCUIT_BLOCK_THRESHOLD: int = int(os.getenv("CIRCUIT_BLOCK_THRESHOLD", "3"))
_cooldown_raw = os.getenv("COOLDOWN_STEPS_MINUTES", "10,20,40")
COOLDOWN_STEPS_MINUTES: list[int] = [int(x.strip()) for x in _cooldown_raw.split(",") if x.strip().isdigit()] or [10, 20, 40]

# При полном провале парсинга — сохранить файл с поисковыми ссылками / сниппетами (см. app/utils/error_research.py)
RESEARCH_ON_PARSE_FAILURE: bool = os.getenv("RESEARCH_ON_PARSE_FAILURE", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# @skills: config-env-loader, logging-rotating-file
# ── Логирование ───────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = os.getenv("LOG_FILE", "parser.log")


def setup_logger(name: str = "parser") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(LOG_LEVEL)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(str(log_path), maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


logger = setup_logger()
