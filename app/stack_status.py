"""Runtime stack and production-readiness checks."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from importlib import metadata

from app.config import AI_ENABLED, AI_PROVIDER, DATABASE_URL, MARKETMIND_WORKSPACE_DIR, RUNTIME_DATA_DIR


@dataclass(frozen=True)
class StackComponent:
    layer: str
    technology: str
    version: str
    status: str = "active"

    def to_dict(self) -> dict[str, str]:
        return {
            "layer": self.layer,
            "technology": self.technology,
            "version": self.version,
            "status": self.status,
        }


@dataclass(frozen=True)
class ReadinessCheck:
    key: str
    title: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }


def _package_version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not installed"


def database_backend(database_url: str = DATABASE_URL) -> str:
    if database_url.startswith("sqlite"):
        return "sqlite"
    if database_url.startswith("postgresql"):
        return "postgresql"
    return database_url.split(":", 1)[0] or "unknown"


def runtime_stack() -> list[dict[str, str]]:
    components = [
        StackComponent("language", "Python", sys.version.split()[0]),
        StackComponent("backend", "FastAPI", _package_version("fastapi")),
        StackComponent("server", "Uvicorn", _package_version("uvicorn")),
        StackComponent("database", f"SQLAlchemy async / {database_backend()}", _package_version("SQLAlchemy")),
        StackComponent("ui", "Jinja2 + HTMX", f"{_package_version('Jinja2')} / vendored"),
        StackComponent("telegram", "aiogram", _package_version("aiogram")),
        StackComponent("scraping", "Playwright", _package_version("playwright")),
        StackComponent("http", "httpx / aiohttp", f"{_package_version('httpx')} / {_package_version('aiohttp')}"),
        StackComponent("imports", "pandas / openpyxl", f"{_package_version('pandas')} / {_package_version('openpyxl')}"),
        StackComponent("quality", "pytest / Ruff", f"{_package_version('pytest')} / {_package_version('ruff')}"),
    ]
    return [component.to_dict() for component in components]


def readiness_checks(*, schema_version: str | None = None) -> list[dict[str, str]]:
    backend = database_backend()
    has_alembic_revision = bool(schema_version and schema_version not in {"create_all", "not initialized", "unknown"})
    checks = [
        ReadinessCheck(
            "python-runtime",
            "Python runtime",
            "ok" if sys.version_info >= (3, 12) else "action",
            "Python 3.12+ is the preferred runtime for async/parsing workloads.",
        ),
        ReadinessCheck(
            "database-backend",
            "Database backend",
            "ok" if backend == "postgresql" else "warn",
            "SQLite is fine for local work; PostgreSQL + asyncpg is recommended for production.",
        ),
        ReadinessCheck(
            "schema-migrations",
            "Schema migrations",
            "ok" if has_alembic_revision else "warn",
            "Alembic should be the source of truth before production schema changes.",
        ),
        ReadinessCheck(
            "runtime-data",
            "Runtime data directory",
            "ok" if RUNTIME_DATA_DIR.exists() and MARKETMIND_WORKSPACE_DIR.exists() else "warn",
            "Runtime and workspace paths should be explicit, writable and outside temporary storage.",
        ),
        ReadinessCheck(
            "ai-provider",
            "AI provider",
            "ok" if AI_ENABLED else "warn",
            f"AI provider is configured as {AI_PROVIDER}; enable AI explicitly for AI-assisted workflows.",
        ),
        ReadinessCheck(
            "job-runner",
            "Background jobs",
            "ok",
            "Persistent job records are available; Redis-backed execution can be added behind this contract.",
        ),
        ReadinessCheck(
            "observability",
            "Observability",
            "warn",
            "Scrape telemetry exists; structured logs, trace ids and error reporting are still needed.",
        ),
    ]
    return [check.to_dict() for check in checks]
