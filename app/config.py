import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


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


def _path_from_env(key: str, default: Path | str) -> Path:
    raw = os.getenv(key, "").strip()
    path = Path(raw) if raw else Path(default)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _runtime_data_dir() -> Path:
    explicit = os.getenv("MARKETMIND_DATA_DIR", "").strip()
    preferred = _path_from_env("MARKETMIND_DATA_DIR", PROJECT_ROOT / "app" / "data")
    if explicit or _is_writable_dir(preferred):
        return preferred
    fallback = Path(tempfile.gettempdir()) / "marketmind"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


# ── Telegram ──────────────────────────────────────────────────────────────────
def _env_bool(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]
TELEGRAM_DROP_PENDING_UPDATES: bool = _env_bool("TELEGRAM_DROP_PENDING_UPDATES", "0")
TELEGRAM_FORCE_DIRECT: bool = _env_bool("TELEGRAM_FORCE_DIRECT", "0")


def require_bot_token() -> str:
    return _require("BOT_TOKEN")

# ── Claude AI ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")  # legacy
GROK_API_KEY: str = os.getenv("GROK_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "grok")  # grok / claude / gemini
AI_ENABLED: bool = _env_bool("AI_ENABLED", "0")

# ── AI provider keys ─────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
MIMO_API_KEY: str = os.getenv("MIMO_API_KEY", "")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "")
AI_FALLBACK_PROVIDERS: list[str] = [
    p.strip() for p in os.getenv("AI_FALLBACK_PROVIDERS", "").split(",") if p.strip()
]

# ── Runtime paths ─────────────────────────────────────────────────────────────
RUNTIME_DATA_DIR: Path = _runtime_data_dir()
REPORTS_DIR: Path = _path_from_env("REPORTS_DIR", RUNTIME_DATA_DIR / "reports")
PARSER_DEBUG_DIR: Path = _path_from_env("PARSER_DEBUG_DIR", RUNTIME_DATA_DIR / "debug")
OZON_PROFILE_DIR: Path = _path_from_env("OZON_PROFILE_DIR", RUNTIME_DATA_DIR / "ozon_profile")
MARKETMIND_WORKSPACE_DIR: Path = _path_from_env("MARKETMIND_WORKSPACE_DIR", RUNTIME_DATA_DIR / "workspace")
SCRAPE_ATTEMPTS_JSONL: Path = _path_from_env("SCRAPE_ATTEMPTS_JSONL", RUNTIME_DATA_DIR / "scrape_attempts.jsonl")
BLOCK_PATTERNS_JSONL: Path = _path_from_env("BLOCK_PATTERNS_JSONL", RUNTIME_DATA_DIR / "blocked_patterns.jsonl")

# ── Local client workflow limits ─────────────────────────────────────────────
IMPORT_SCHEMA_VERSION: str = os.getenv("IMPORT_SCHEMA_VERSION", "local-import-v1")
EXPORT_SCHEMA_VERSION: str = os.getenv("EXPORT_SCHEMA_VERSION", "local-export-v1")
IMPORT_MAX_FILE_BYTES: int = int(os.getenv("IMPORT_MAX_FILE_BYTES", str(20 * 1024 * 1024)))
IMPORT_MAX_ROWS: int = int(os.getenv("IMPORT_MAX_ROWS", "10000"))
IMPORT_MAX_CELL_CHARS: int = int(os.getenv("IMPORT_MAX_CELL_CHARS", "20000"))
IMPORT_PREVIEW_ROWS: int = int(os.getenv("IMPORT_PREVIEW_ROWS", "5"))

# ── База данных ───────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{(RUNTIME_DATA_DIR / 'parser.db').as_posix()}")
if DATABASE_URL.startswith("sqlite+aiosqlite:///"):
    _db_path = Path(DATABASE_URL.removeprefix("sqlite+aiosqlite:///"))
    if not _db_path.is_absolute():
        _db_path = PROJECT_ROOT / _db_path
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
LOG_FILE: str = os.getenv("LOG_FILE", str(RUNTIME_DATA_DIR / "logs" / "parser.log"))


def setup_logger(name: str = "parser") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(LOG_LEVEL)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    log_path = Path(LOG_FILE)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(log_path), maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError as exc:
        logger.warning("File logging disabled: cannot open %s (%s)", log_path, exc)
    return logger


logger = setup_logger()
