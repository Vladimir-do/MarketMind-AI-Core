"""Alembic helpers for explicit database schema management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.config import DATABASE_URL, PROJECT_ROOT


@dataclass(frozen=True)
class MigrationStatus:
    current_revision: str
    head_revision: str
    is_current: bool

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "current_revision": self.current_revision,
            "head_revision": self.head_revision,
            "is_current": self.is_current,
        }


def alembic_config(database_url: str = DATABASE_URL) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def migration_head(database_url: str = DATABASE_URL) -> str:
    script = ScriptDirectory.from_config(alembic_config(database_url))
    head = script.get_current_head()
    return str(head or "none")


def _sync_inspection_url(database_url: str) -> str | None:
    if database_url.startswith("sqlite+aiosqlite:///"):
        return f"sqlite:///{database_url.removeprefix('sqlite+aiosqlite:///')}"
    if database_url == "sqlite+aiosqlite://":
        return "sqlite://"
    return None


def current_revision(database_url: str = DATABASE_URL) -> str:
    sync_url = _sync_inspection_url(database_url)
    if sync_url is None:
        return "unknown"
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            revision = context.get_current_revision()
            return str(revision or "not initialized")
    finally:
        engine.dispose()


def migration_status(database_url: str = DATABASE_URL) -> MigrationStatus:
    head = migration_head(database_url)
    current = current_revision(database_url)
    return MigrationStatus(
        current_revision=current,
        head_revision=head,
        is_current=current == head,
    )


def upgrade_database(database_url: str = DATABASE_URL, revision: str = "head") -> MigrationStatus:
    url = database_url
    if url.startswith("sqlite+aiosqlite:///"):
        path = Path(url.removeprefix("sqlite+aiosqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(url), revision)
    return migration_status(url)
