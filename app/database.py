import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship

from app.compat.aiosqlite_patch import apply_aiosqlite_future_poll_patch
from app.config import BLOCK_PATTERNS_JSONL, DATABASE_URL, SCRAPE_ATTEMPTS_JSONL, logger
from app.utils.proxy import mask_proxy_url

apply_aiosqlite_future_poll_patch()

Base = declarative_base()


# ── Модели ────────────────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id         = Column(Integer, primary_key=True)
    url_hash   = Column(String(32), unique=True, nullable=False)
    url        = Column(Text, nullable=False)
    name       = Column(Text)
    image_url  = Column(Text)
    first_seen = Column(DateTime, default=lambda: datetime.now(UTC))
    last_check = Column(DateTime, default=lambda: datetime.now(UTC))

    history = relationship("PriceHistory", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_products_url_hash", "url_hash"),)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id                  = Column(Integer, primary_key=True)
    product_id          = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    price               = Column(Integer)           # рубли, целое; None = недоступен
    availability_status = Column(String(20), nullable=False)  # in_stock / out_of_stock / deleted / blocked
    recorded_at         = Column(DateTime, default=lambda: datetime.now(UTC), index=True)

    product = relationship("Product", back_populates="history")

    __table_args__ = (
        Index("ix_price_history_product_id", "product_id"),
        Index("ix_price_history_product_recorded", "product_id", "recorded_at"),
    )


class ScrapeAttempt(Base):
    __tablename__ = "scrape_attempts"

    id          = Column(Integer, primary_key=True)
    job_id      = Column(Integer, default=0)
    product_id  = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"))
    url         = Column(Text, nullable=False)
    site        = Column(Text)
    marketplace = Column(String(32), nullable=False)
    task_type   = Column(String(80))
    parser_used = Column(String(120))
    fetch_status = Column(String(32))
    source      = Column(String(32), nullable=False)
    status      = Column(String(32), nullable=False)
    success     = Column(Boolean)
    http_status = Column(Integer)
    latency_ms  = Column(Integer, nullable=False)
    proxy       = Column(Text)
    browser_profile = Column(Text)
    strategy    = Column(String(80))
    warnings    = Column(Text)
    confidence  = Column(Float)
    next_best_strategy = Column(String(120))
    error_class = Column(String(120))
    error_text  = Column(Text)
    errors      = Column(Text)
    created_at  = Column(DateTime, default=lambda: datetime.now(UTC))
    recorded_at = Column(DateTime, default=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        Index("ix_scrape_attempts_marketplace_recorded", "marketplace", "recorded_at"),
        Index("ix_scrape_attempts_product_id", "product_id"),
    )


class BlockedPattern(Base):
    __tablename__ = "blocked_patterns"

    id              = Column(Integer, primary_key=True)
    url_hash        = Column(String(32), index=True)
    url             = Column(Text)
    marketplace     = Column(String(32), nullable=False, index=True)
    source          = Column(String(32), nullable=False)
    status          = Column(String(32), nullable=False)
    trigger         = Column(String(80), nullable=False)
    proxy           = Column(Text)
    browser_profile = Column(Text)
    strategy        = Column(String(80))
    cooldown_sec    = Column(Integer, default=0)
    http_status     = Column(Integer)
    latency_ms      = Column(Integer, default=0)
    error_class     = Column(String(120))
    error_text      = Column(Text)
    recorded_at     = Column(DateTime, default=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        Index("ix_blocked_patterns_marketplace_recorded", "marketplace", "recorded_at"),
        Index("ix_blocked_patterns_trigger_recorded", "trigger", "recorded_at"),
    )


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class ClientProject(Base):
    __tablename__ = "client_projects"

    project_id         = Column(String(64), primary_key=True)
    name               = Column(Text, nullable=False)
    client_name        = Column(Text)
    marketplace        = Column(String(32), nullable=False, default="unknown")
    status             = Column(String(32), nullable=False, default="new")
    description        = Column(Text)
    source_filename    = Column(Text)
    source_file_hash   = Column(String(64))
    source_imported_at = Column(DateTime)
    created_at         = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at         = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    completed_at       = Column(DateTime)
    notes              = Column(Text)
    export_directory   = Column(Text)

    __table_args__ = (
        Index("ix_client_projects_status_updated", "status", "updated_at"),
    )


class ClientProjectFile(Base):
    __tablename__ = "client_project_files"

    file_id           = Column(String(64), primary_key=True)
    project_id        = Column(String(64), ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False)
    original_filename = Column(Text, nullable=False)
    stored_filename   = Column(Text, nullable=False)
    relative_path     = Column(Text, nullable=False)
    sha256            = Column(String(64), nullable=False)
    size_bytes        = Column(Integer, nullable=False)
    file_format       = Column(String(16), nullable=False)
    schema_version    = Column(String(32), nullable=False, default="local-import-v1")
    encoding          = Column(String(64))
    delimiter         = Column(String(8))
    selected_sheet    = Column(Text)
    row_count         = Column(Integer)
    successful_rows   = Column(Integer, nullable=False, default=0)
    warning_count     = Column(Integer, nullable=False, default=0)
    error_count       = Column(Integer, nullable=False, default=0)
    import_status     = Column(String(32), nullable=False, default="pending")
    import_errors_json = Column(Text)
    import_summary_json = Column(Text)
    imported_at       = Column(DateTime)
    created_at        = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_client_project_files_project_sha256"),
        Index("ix_client_project_files_project_created", "project_id", "created_at"),
    )


class ImportMappingPreset(Base):
    __tablename__ = "import_mapping_presets"

    preset_id           = Column(String(64), primary_key=True)
    project_id          = Column(String(64), ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False)
    name                = Column(Text, nullable=False)
    marketplace         = Column(String(32), nullable=False, default="unknown")
    schema_version      = Column(String(32), nullable=False, default="local-import-v1")
    source_columns_json = Column(Text, nullable=False)
    mapping_json        = Column(Text, nullable=False)
    header_fingerprint  = Column(String(64), nullable=False)
    active              = Column(Boolean, nullable=False, default=True)
    created_at          = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    last_used_at        = Column(DateTime)

    __table_args__ = (
        Index("ix_import_mapping_presets_project_active", "project_id", "active"),
        Index("ix_import_mapping_presets_project_fingerprint", "project_id", "header_fingerprint"),
    )


class ProjectProduct(Base):
    __tablename__ = "project_products"

    project_product_id          = Column(String(64), primary_key=True)
    project_id                  = Column(String(64), ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False)
    product_id                  = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    source_file_id              = Column(String(64), ForeignKey("client_project_files.file_id", ondelete="SET NULL"))
    source_row_index            = Column(Integer)
    source_snapshot_json        = Column(Text, nullable=False)
    source_snapshot_hash        = Column(String(64), nullable=False)
    latest_source_snapshot_json = Column(Text, nullable=False)
    latest_source_snapshot_hash = Column(String(64), nullable=False)
    status                      = Column(String(32), nullable=False, default="active")
    created_at                  = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at                  = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    source_updated_at           = Column(DateTime)
    effective_updated_at        = Column(DateTime)

    product = relationship("Product")

    __table_args__ = (
        UniqueConstraint("project_id", "product_id", name="uq_project_products_project_product"),
        Index("ix_project_products_project_updated", "project_id", "updated_at"),
        Index("ix_project_products_product_id", "product_id"),
    )


class ProjectExport(Base):
    __tablename__ = "project_exports"

    export_id           = Column(String(64), primary_key=True)
    project_id          = Column(String(64), ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False)
    export_type         = Column(String(32), nullable=False)
    marketplace_profile = Column(String(32), nullable=False)
    file_format         = Column(String(16), nullable=False)
    schema_version      = Column(String(32), nullable=False, default="local-export-v1")
    relative_path       = Column(Text, nullable=False)
    product_count       = Column(Integer, nullable=False, default=0)
    checksum            = Column(String(64))
    manifest_json       = Column(Text)
    status              = Column(String(32), nullable=False, default="created")
    warnings_json       = Column(Text)
    created_at          = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_project_exports_project_created", "project_id", "created_at"),
    )


class ProjectReport(Base):
    __tablename__ = "project_reports"

    report_id     = Column(String(64), primary_key=True)
    project_id    = Column(String(64), ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False)
    report_type   = Column(String(32), nullable=False)
    file_format   = Column(String(16), nullable=False)
    relative_path = Column(Text, nullable=False)
    summary_json  = Column(Text, nullable=False)
    status        = Column(String(32), nullable=False, default="created")
    created_at    = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_project_reports_project_created", "project_id", "created_at"),
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id              = Column(Integer, primary_key=True)
    approval_id     = Column(String(32), unique=True, nullable=False)
    product_id      = Column(String(128), nullable=False)
    field           = Column(String(64), nullable=False)
    suggestion_type = Column(String(32), nullable=False)
    before_value    = Column(Text)
    after_value     = Column(Text, nullable=False)
    reason          = Column(Text, nullable=False)
    confidence      = Column(Float, nullable=False)
    source_finding  = Column(String(128))
    metadata_json   = Column(Text)  # JSON: suggestion metadata (product_name, etc.)
    status          = Column(String(16), nullable=False, default="pending")
    reject_reason   = Column(Text)
    snapshot_before = Column(Text)  # JSON: value before apply
    snapshot_after  = Column(Text)  # JSON: value after apply
    created_at      = Column(DateTime, default=lambda: datetime.now(UTC))
    reviewed_at     = Column(DateTime)
    applied_at      = Column(DateTime)
    rolled_back_at  = Column(DateTime)

    __table_args__ = (
        Index("ix_approval_records_status", "status"),
        Index("ix_approval_records_product_id", "product_id"),
        Index("ix_approval_records_created_at", "created_at"),
        Index("ix_approval_records_product_created", "product_id", "created_at"),
    )


class ProductCardDraft(Base):
    __tablename__ = "product_card_drafts"

    draft_id        = Column(String(64), primary_key=True)
    product_id      = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    project_id      = Column(String(64), ForeignKey("client_projects.project_id", ondelete="SET NULL"))
    project_product_id = Column(String(64), ForeignKey("project_products.project_product_id", ondelete="SET NULL"))
    base_version_id = Column(String(128))
    status          = Column(String(32), nullable=False, default="draft")
    payload_json    = Column(Text, nullable=False)
    validation_json = Column(Text)
    created_by      = Column(String(128))
    created_at      = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at      = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    revision        = Column(Integer, nullable=False, default=1)
    comment         = Column(Text)

    product = relationship("Product")

    __table_args__ = (
        Index("ix_product_card_drafts_product_status_updated", "product_id", "status", "updated_at"),
        Index("ix_product_card_drafts_product_id", "product_id"),
        Index("ix_product_card_drafts_project_product_status", "project_id", "project_product_id", "status"),
    )


class ProductCardVersion(Base):
    __tablename__ = "product_card_versions"

    version_id              = Column(String(128), primary_key=True)
    product_id              = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    project_id              = Column(String(64), ForeignKey("client_projects.project_id", ondelete="SET NULL"))
    project_product_id      = Column(String(64), ForeignKey("project_products.project_product_id", ondelete="SET NULL"))
    version_number          = Column(Integer, nullable=False)
    snapshot_json           = Column(Text, nullable=False)
    snapshot_schema_version = Column(Integer, nullable=False, default=1)
    source                  = Column(String(32), nullable=False)
    actor_type              = Column(String(32), nullable=False)
    actor_id                = Column(String(128))
    comment                 = Column(Text)
    created_at              = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    base_version_id         = Column(String(128))
    trigger_event_id        = Column(String(128))
    checksum                = Column(String(64), nullable=False)

    product = relationship("Product")

    __table_args__ = (
        Index("ix_product_card_versions_product_number", "product_id", "version_number", unique=True),
        Index("ix_product_card_versions_product_created", "product_id", "created_at"),
        Index("ix_product_card_versions_trigger_event_id", "trigger_event_id"),
        Index("ix_product_card_versions_project_product_number", "project_id", "project_product_id", "version_number"),
    )


class ContentPipelineArtifact(Base):
    __tablename__ = "content_pipeline_artifacts"

    artifact_id       = Column(String(64), primary_key=True)
    project_id        = Column(String(64), ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False)
    project_product_id = Column(String(64), ForeignKey("project_products.project_product_id", ondelete="CASCADE"), nullable=False)
    product_id        = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    artifact_type     = Column(String(32), nullable=False)  # content_strategy | semantic_plan | fact_check_report | quality_report
    version_number    = Column(Integer, nullable=False)
    payload_json      = Column(Text, nullable=False)
    schema_version    = Column(Integer, nullable=False, default=1)
    prompt_id         = Column(String(64))
    prompt_version    = Column(String(16))
    model_used        = Column(String(64))
    job_id            = Column(String(64), ForeignKey("job_records.job_id", ondelete="SET NULL"))
    created_at        = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index(
            "ix_cpa_project_product_type_version",
            "project_id", "project_product_id", "artifact_type", "version_number",
            unique=True,
        ),
        Index("ix_cpa_product_type_created", "product_id", "artifact_type", "created_at"),
    )


class CompetitorSnapshot(Base):
    __tablename__ = "competitor_snapshots"

    snapshot_id       = Column(String(64), primary_key=True)
    batch_id          = Column(String(64), nullable=False)
    project_id        = Column(String(64), ForeignKey("client_projects.project_id", ondelete="CASCADE"), nullable=False)
    project_product_id = Column(String(64), ForeignKey("project_products.project_product_id", ondelete="CASCADE"), nullable=False)
    product_id        = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    marketplace       = Column(String(32), nullable=False)
    competitor_name   = Column(Text, nullable=False)
    competitor_url    = Column(Text, nullable=False)
    price             = Column(Integer)
    old_price         = Column(Integer)
    rating            = Column(Float)
    reviews_count     = Column(Integer)
    reviews_json      = Column(Text)
    search_query      = Column(Text, nullable=False)
    created_at        = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_competitor_snapshots_batch", "batch_id"),
        Index("ix_competitor_snapshots_project_product_created", "project_id", "project_product_id", "created_at"),
        Index("ix_competitor_snapshots_product_id", "product_id"),
    )


class DomainEventRecord(Base):
    __tablename__ = "domain_event_records"

    event_id       = Column(String(128), primary_key=True)
    aggregate_type = Column(String(64), nullable=False)
    aggregate_id   = Column(Text, nullable=False)
    event_type     = Column(String(128), nullable=False)
    source         = Column(String(32), nullable=False)
    actor_type     = Column(String(32), nullable=False)
    actor_id       = Column(String(128))
    occurred_at    = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    payload_json   = Column(Text, nullable=False)
    metadata_json  = Column(Text, nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    correlation_id = Column(String(128))
    causation_id   = Column(String(128))
    created_at     = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_domain_event_records_aggregate_time", "aggregate_type", "aggregate_id", "occurred_at"),
        Index("ix_domain_event_records_event_type_time", "event_type", "occurred_at"),
        Index("ix_domain_event_records_correlation_id", "correlation_id"),
    )


class JobRecord(Base):
    __tablename__ = "job_records"

    job_id       = Column(String(64), primary_key=True)
    job_type     = Column(String(80), nullable=False, index=True)
    status       = Column(String(32), nullable=False, default="queued", index=True)
    payload_json = Column(Text, nullable=False)
    result_json  = Column(Text)
    error_class  = Column(String(120))
    error_text   = Column(Text)
    progress     = Column(Integer, nullable=False, default=0)
    created_at   = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    started_at   = Column(DateTime)
    finished_at  = Column(DateTime)
    updated_at   = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    __table_args__ = (
        Index("ix_job_records_status_updated", "status", "updated_at"),
        Index("ix_job_records_type_created", "job_type", "created_at"),
    )


# ── Вспомогательные функции ───────────────────────────────────────────────────

def url_to_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _scrape_attempts_jsonl_path() -> Path | None:
    raw = os.getenv("SCRAPE_ATTEMPTS_JSONL", "").strip()
    if not raw:
        return SCRAPE_ATTEMPTS_JSONL
    return Path(raw)


def _block_patterns_jsonl_path() -> Path | None:
    raw = os.getenv("BLOCK_PATTERNS_JSONL", "").strip()
    if not raw:
        return BLOCK_PATTERNS_JSONL
    return Path(raw)


def _site_from_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    return (urlparse(url).netloc or "").lower() or None


def _text_payload(value: str | list[str] | tuple[str, ...] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value[:1000] if value else None
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        return None
    return json.dumps(items, ensure_ascii=False)[:1000]


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


# ── Database класс ────────────────────────────────────────────────────────────

class Database:
    def __init__(self):
        self._engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self):
        """Инициализирует базу данных.

        NOTE: В будущем create_all будет заменен Alembic миграциями.
        Запускайте `alembic upgrade head` для управления схемой.
        Пока create_all остается для обратной совместимости со старыми БД и тестами.
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if DATABASE_URL.startswith("sqlite"):
                await conn.execute(text("PRAGMA journal_mode=WAL"))
            # NOTE: _migrate_scrape_attempts() будет заменена Alembic в будущем
            await self._migrate_scrape_attempts(conn)
        logger.info("База данных инициализирована")

    def session(self) -> AsyncSession:
        return self._session_factory()

    async def _migrate_scrape_attempts(self, conn) -> None:
        if not DATABASE_URL.startswith("sqlite"):
            return

        rows = await conn.exec_driver_sql("PRAGMA table_info(scrape_attempts)")
        columns = {row[1] for row in rows.fetchall()}
        if not columns:
            return

        migrations = {
            "product_id": "ALTER TABLE scrape_attempts ADD COLUMN product_id INTEGER",
            "site": "ALTER TABLE scrape_attempts ADD COLUMN site TEXT",
            "task_type": "ALTER TABLE scrape_attempts ADD COLUMN task_type VARCHAR(80)",
            "parser_used": "ALTER TABLE scrape_attempts ADD COLUMN parser_used VARCHAR(120)",
            "source": "ALTER TABLE scrape_attempts ADD COLUMN source VARCHAR(32)",
            "status": "ALTER TABLE scrape_attempts ADD COLUMN status VARCHAR(32)",
            "success": "ALTER TABLE scrape_attempts ADD COLUMN success BOOLEAN",
            "recorded_at": "ALTER TABLE scrape_attempts ADD COLUMN recorded_at DATETIME",
            "proxy": "ALTER TABLE scrape_attempts ADD COLUMN proxy TEXT",
            "browser_profile": "ALTER TABLE scrape_attempts ADD COLUMN browser_profile TEXT",
            "strategy": "ALTER TABLE scrape_attempts ADD COLUMN strategy VARCHAR(80)",
            "warnings": "ALTER TABLE scrape_attempts ADD COLUMN warnings TEXT",
            "confidence": "ALTER TABLE scrape_attempts ADD COLUMN confidence FLOAT",
            "next_best_strategy": "ALTER TABLE scrape_attempts ADD COLUMN next_best_strategy VARCHAR(120)",
            "errors": "ALTER TABLE scrape_attempts ADD COLUMN errors TEXT",
        }
        for column, sql in migrations.items():
            if column not in columns:
                await conn.exec_driver_sql(sql)

        if "fetch_status" in columns:
            await conn.exec_driver_sql(
                "UPDATE scrape_attempts SET status = COALESCE(status, fetch_status)"
            )
        if "created_at" in columns:
            await conn.exec_driver_sql(
                "UPDATE scrape_attempts SET recorded_at = COALESCE(recorded_at, created_at)"
            )
        await conn.exec_driver_sql(
            "UPDATE scrape_attempts SET source = COALESCE(source, 'legacy')"
        )
        await conn.exec_driver_sql(
            "UPDATE scrape_attempts SET success = COALESCE(success, CASE WHEN status = 'ok' THEN 1 ELSE 0 END)"
        )

    async def get_all_products(self) -> list[Product]:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(Product))
            return result.scalars().all()

    async def get_latest_product(self) -> Product | None:
        from sqlalchemy import desc, select

        async with self.session() as s:
            result = await s.execute(
                select(Product)
                .order_by(desc(Product.last_check), desc(Product.id))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def create_job(self, job_type: str, payload: dict | None = None, *, job_id: str | None = None) -> JobRecord:
        now = datetime.now(UTC)
        record = JobRecord(
            job_id=job_id or uuid.uuid4().hex,
            job_type=job_type,
            status="queued",
            payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            progress=0,
            created_at=now,
            updated_at=now,
        )
        async with self.session() as s:
            s.add(record)
            await s.commit()
            await s.refresh(record)
            return record

    async def start_job(self, job_id: str) -> JobRecord | None:
        now = datetime.now(UTC)
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.status = "running"
            record.started_at = record.started_at or now
            record.updated_at = now
            await s.commit()
            await s.refresh(record)
            return record

    async def update_job_progress(self, job_id: str, progress: int) -> JobRecord | None:
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.progress = max(0, min(100, int(progress)))
            record.updated_at = datetime.now(UTC)
            await s.commit()
            await s.refresh(record)
            return record

    async def finish_job(self, job_id: str, result: dict | None = None) -> JobRecord | None:
        now = datetime.now(UTC)
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.status = "succeeded"
            record.progress = 100
            record.result_json = json.dumps(result or {}, ensure_ascii=False, sort_keys=True)
            record.finished_at = now
            record.updated_at = now
            await s.commit()
            await s.refresh(record)
            return record

    async def fail_job(
        self,
        job_id: str,
        error: Exception | str,
        *,
        details: dict | None = None,
    ) -> JobRecord | None:
        now = datetime.now(UTC)
        error_class = error.__class__.__name__ if isinstance(error, Exception) else "JobError"
        error_text = str(error)[:1000]
        async with self.session() as s:
            record = await s.get(JobRecord, job_id)
            if record is None:
                return None
            record.status = "failed"
            record.error_class = error_class
            record.error_text = error_text
            if details is not None:
                record.result_json = json.dumps(details, ensure_ascii=False, sort_keys=True)
            record.finished_at = now
            record.updated_at = now
            await s.commit()
            await s.refresh(record)
            return record

    async def get_recent_jobs(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[JobRecord]:
        from sqlalchemy import desc, select

        stmt = select(JobRecord).order_by(desc(JobRecord.updated_at)).limit(limit)
        if status:
            stmt = stmt.where(JobRecord.status == status)
        if job_type:
            stmt = stmt.where(JobRecord.job_type == job_type)
        async with self.session() as s:
            result = await s.execute(stmt)
            return result.scalars().all()

    async def get_product_by_hash(self, url_hash: str) -> Product | None:
        from sqlalchemy import select
        async with self.session() as s:
            result = await s.execute(select(Product).where(Product.url_hash == url_hash))
            return result.scalar_one_or_none()

    async def get_last_price(self, product_id: int) -> PriceHistory | None:
        from sqlalchemy import desc, select
        async with self.session() as s:
            result = await s.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id == product_id)
                .order_by(desc(PriceHistory.recorded_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def record_scrape_attempt(
        self,
        *,
        url: str,
        marketplace: str,
        source: str,
        status: str,
        latency_ms: int,
        product_id: int | None = None,
        site: str | None = None,
        task_type: str | None = None,
        parser_used: str | None = None,
        success: bool | None = None,
        http_status: int | None = None,
        error_class: str | None = None,
        error_text: str | None = None,
        errors: str | list[str] | tuple[str, ...] | None = None,
        warnings: str | list[str] | tuple[str, ...] | None = None,
        confidence: float | None = None,
        next_best_strategy: str | None = None,
        trigger: str | None = None,
        proxy: str | None = None,
        browser_profile: str | None = None,
        strategy: str | None = None,
        cooldown_sec: int = 0,
    ) -> None:
        now = datetime.now(UTC)
        latency_ms = max(0, int(latency_ms))
        proxy = mask_proxy_url(proxy) if proxy else None
        error_text = error_text[:1000] if error_text else None
        errors_text = _text_payload(errors) or error_text
        warnings_text = _text_payload(warnings)
        site = site or _site_from_url(url) or marketplace
        task_type = task_type or "marketplace_product"
        parser_used = parser_used or marketplace
        success = (status == "ok") if success is None else bool(success)
        confidence = (0.9 if success else 0.0) if confidence is None else max(0.0, min(1.0, float(confidence)))
        next_best_strategy = next_best_strategy or _next_best_strategy_for(source, status)
        trigger = trigger or _classify_failure_trigger(
            status=status,
            http_status=http_status,
            error_class=error_class,
            error_text=errors_text or error_text,
        )
        async with self.session() as s:
            s.add(ScrapeAttempt(
                job_id=0,
                product_id=product_id,
                url=url,
                site=site,
                marketplace=marketplace,
                task_type=task_type,
                parser_used=parser_used,
                fetch_status=status,
                source=source,
                status=status,
                success=success,
                http_status=http_status,
                latency_ms=latency_ms,
                proxy=proxy,
                browser_profile=browser_profile,
                strategy=strategy,
                warnings=warnings_text,
                confidence=confidence,
                next_best_strategy=next_best_strategy,
                error_class=error_class,
                error_text=error_text,
                errors=errors_text,
                created_at=now,
                recorded_at=now,
            ))
            if trigger:
                s.add(BlockedPattern(
                    recorded_at=now,
                    url=url,
                    url_hash=url_to_hash(url) if url else None,
                    marketplace=marketplace,
                    source=source,
                    status=status,
                    trigger=trigger,
                    proxy=proxy,
                    browser_profile=browser_profile,
                    strategy=strategy,
                    cooldown_sec=max(0, int(cooldown_sec or 0)),
                    http_status=http_status,
                    latency_ms=max(0, int(latency_ms or 0)),
                    error_class=error_class,
                    error_text=(error_text[:1000] if error_text else None),
                ))
            await s.commit()
        if trigger:
            self._append_blocked_pattern_jsonl(
                {
                    "recorded_at": now.isoformat(),
                    "url": url,
                    "url_hash": url_to_hash(url) if url else None,
                    "marketplace": marketplace,
                    "source": source,
                    "status": status,
                    "trigger": trigger,
                    "proxy": proxy,
                    "browser_profile": browser_profile,
                    "strategy": strategy,
                    "cooldown_sec": max(0, int(cooldown_sec or 0)),
                    "http_status": http_status,
                    "latency_ms": max(0, int(latency_ms or 0)),
                    "error_class": error_class,
                    "error_text": (error_text[:1000] if error_text else None),
                }
            )
        self._append_scrape_attempt_jsonl(
            {
                "recorded_at": now.isoformat(),
                "product_id": product_id,
                "url": url,
                "site": site,
                "marketplace": marketplace,
                "task_type": task_type,
                "parser_used": parser_used,
                "source": source,
                "status": status,
                "success": success,
                "http_status": http_status,
                "latency_ms": latency_ms,
                "proxy": proxy,
                "browser_profile": browser_profile,
                "strategy": strategy,
                "warnings": warnings_text,
                "confidence": confidence,
                "next_best_strategy": next_best_strategy,
                "error_class": error_class,
                "error_text": error_text,
                "errors": errors_text,
            }
        )

    async def record_blocked_pattern(
        self,
        *,
        url: str | None,
        marketplace: str,
        source: str,
        status: str,
        trigger: str,
        proxy: str | None = None,
        browser_profile: str | None = None,
        strategy: str | None = None,
        cooldown_sec: int = 0,
        http_status: int | None = None,
        latency_ms: int = 0,
        error_class: str | None = None,
        error_text: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        proxy = mask_proxy_url(proxy) if proxy else None
        payload = {
            "recorded_at": now,
            "url": url,
            "url_hash": url_to_hash(url) if url else None,
            "marketplace": marketplace,
            "source": source,
            "status": status,
            "trigger": trigger,
            "proxy": proxy,
            "browser_profile": browser_profile,
            "strategy": strategy,
            "cooldown_sec": max(0, int(cooldown_sec or 0)),
            "http_status": http_status,
            "latency_ms": max(0, int(latency_ms or 0)),
            "error_class": error_class,
            "error_text": (error_text[:1000] if error_text else None),
        }
        try:
            async with self.session() as s:
                s.add(BlockedPattern(**payload))
                await s.commit()
        except Exception:
            logger.warning(
                "blocked pattern write failed (marketplace=%s trigger=%s): "
                "adaptive cooldown/circuit-breaker data may be incomplete",
                marketplace, trigger, exc_info=True,
            )
            return
        json_payload = {**payload, "recorded_at": now.isoformat()}
        self._append_blocked_pattern_jsonl(json_payload)

    def _append_blocked_pattern_jsonl(self, payload: dict) -> None:
        path = _block_patterns_jsonl_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            logger.warning("blocked pattern jsonl write failed (path=%s)", path, exc_info=True)

    def _append_scrape_attempt_jsonl(self, payload: dict) -> None:
        path = _scrape_attempts_jsonl_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            logger.warning("scrape_attempts jsonl write failed (path=%s)", path, exc_info=True)

    async def get_recent_scrape_attempts(
        self,
        limit: int = 100,
        *,
        marketplace: str | None = None,
        minutes: int | None = None,
    ) -> list[ScrapeAttempt]:
        from sqlalchemy import desc, select

        stmt = select(ScrapeAttempt).order_by(desc(ScrapeAttempt.recorded_at)).limit(limit)
        if marketplace:
            stmt = stmt.where(ScrapeAttempt.marketplace == marketplace)
        if minutes:
            since = datetime.now(UTC) - timedelta(minutes=minutes)
            stmt = stmt.where(ScrapeAttempt.recorded_at >= since)
        async with self.session() as s:
            result = await s.execute(stmt)
            return result.scalars().all()

    async def get_recent_blocked_patterns(
        self,
        *,
        marketplace: str | None = None,
        limit: int = 100,
        minutes: int | None = None,
    ) -> list[BlockedPattern]:
        from sqlalchemy import desc, select

        stmt = select(BlockedPattern).order_by(desc(BlockedPattern.recorded_at)).limit(limit)
        if marketplace:
            stmt = stmt.where(BlockedPattern.marketplace == marketplace)
        if minutes:
            since = datetime.now(UTC) - timedelta(minutes=minutes)
            stmt = stmt.where(BlockedPattern.recorded_at >= since)
        async with self.session() as s:
            result = await s.execute(stmt)
            return result.scalars().all()

    async def get_marketplace_health(
        self,
        marketplace: str,
        *,
        window_minutes: int | None = None,
    ) -> dict:
        window = window_minutes or _env_int("ADAPTIVE_BLOCK_WINDOW_MINUTES", 60)
        attempts = await self.get_recent_scrape_attempts(
            marketplace=marketplace,
            limit=_env_int("ADAPTIVE_HEALTH_ATTEMPT_LIMIT", 200),
            minutes=window,
        )
        blocks = await self.get_recent_blocked_patterns(
            marketplace=marketplace,
            limit=_env_int("ADAPTIVE_HEALTH_BLOCK_LIMIT", 200),
            minutes=window,
        )

        attempt_count = len(attempts)
        block_count = len(blocks)
        ok_count = sum(1 for item in attempts if item.status == "ok")
        network_count = sum(1 for item in blocks if item.trigger == "network")
        browser_blocks = [item for item in blocks if item.source == "browser"]
        browser_failures = [
            item for item in attempts
            if item.source == "browser" and item.status not in {"ok", "skipped"}
        ]
        api_blocks = [item for item in blocks if item.source in {"api", "html"}]

        block_rate = block_count / max(1, attempt_count + block_count)
        browser_block_rate = len(browser_blocks) / max(1, block_count)
        network_rate = network_count / max(1, block_count)
        heat_score = min(
            1.0,
            (block_rate * 0.55)
            + (browser_block_rate * 0.2)
            + (network_rate * 0.15)
            + (min(block_count, 10) / 10 * 0.1),
        )
        heat_score = round(heat_score, 4)

        def build_source_stats(source: str) -> dict:
            source_attempts = [item for item in attempts if item.source == source]
            source_blocks = [item for item in blocks if item.source == source]
            total = len(source_attempts)
            ok = sum(1 for item in source_attempts if item.status == "ok")
            block_total = len(source_blocks)
            source_block_rate = block_total / max(1, total + block_total)
            success = _success_rate(total, ok)
            return {
                "attempts": total,
                "ok": ok,
                "blocks": block_total,
                "success_rate": success,
                "block_rate": round(source_block_rate, 4),
                "score": _score_source(
                    success_rate=success,
                    block_rate=source_block_rate,
                    heat_score=heat_score,
                    bias=0.05 if source == "search" else 0.0,
                ),
            }

        source_stats = {
            "api": build_source_stats("api"),
            "browser": build_source_stats("browser"),
            "search_fallback": build_source_stats("search"),
        }

        def build_reputation(field: str) -> dict:
            keys = sorted({
                str(getattr(item, field))
                for item in attempts
                if getattr(item, field)
            } | {
                str(getattr(item, field))
                for item in blocks
                if getattr(item, field)
            })
            reputation = {}
            for key in keys:
                key_attempts = [item for item in attempts if str(getattr(item, field) or "") == key]
                key_blocks = [item for item in blocks if str(getattr(item, field) or "") == key]
                total = len(key_attempts)
                ok = sum(1 for item in key_attempts if item.status == "ok")
                block_total = len(key_blocks)
                block_rate = block_total / max(1, total + block_total)
                success = _success_rate(total, ok)
                reputation[key] = {
                    "attempts": total,
                    "ok": ok,
                    "blocks": block_total,
                    "success_rate": success,
                    "block_rate": round(block_rate, 4),
                    "heavily_blocked": block_total >= _env_int("ADAPTIVE_REPUTATION_BLOCK_THRESHOLD", 3)
                    or block_rate >= _env_float("ADAPTIVE_REPUTATION_BLOCK_RATE", 0.6),
                }
            return reputation

        browser_reputation = build_reputation("browser_profile")
        proxy_reputation = build_reputation("proxy")

        best_profile = None
        best_profile_score = -1.0
        for profile, stats in browser_reputation.items():
            if stats["heavily_blocked"]:
                continue
            score = stats["success_rate"] - stats["block_rate"]
            if score > best_profile_score:
                best_profile = profile
                best_profile_score = score

        best_proxy = None
        best_proxy_score = -1.0
        for proxy, stats in proxy_reputation.items():
            if stats["heavily_blocked"]:
                continue
            score = stats["success_rate"] - stats["block_rate"]
            if score > best_proxy_score:
                best_proxy = proxy
                best_proxy_score = score

        dynamic_cooldown_sec = _adaptive_cooldown(block_count)
        predictive_threshold = _env_float("ADAPTIVE_PREDICTIVE_HEAT_THRESHOLD", 0.9)
        api_disable_threshold = _env_int("ADAPTIVE_API_BLOCK_THRESHOLD", 3)
        return {
            "marketplace": marketplace,
            "window_minutes": window,
            "attempts": attempt_count,
            "ok": ok_count,
            "blocks": block_count,
            "network_failures": network_count,
            "browser_blocks": len(browser_blocks),
            "browser_failures": len(browser_failures),
            "api_blocks": len(api_blocks),
            "heat_score": heat_score,
            "dynamic_cooldown_sec": dynamic_cooldown_sec,
            "predictive_blocking": heat_score >= predictive_threshold,
            "disable_api": len(api_blocks) >= api_disable_threshold,
            "avoid_browser": heat_score >= predictive_threshold
            or len(browser_failures) >= _env_int("ADAPTIVE_BROWSER_FAILURE_THRESHOLD", 3)
            or len(browser_blocks) >= _env_int("ADAPTIVE_BROWSER_BLOCK_THRESHOLD", 3),
            "source_scores": source_stats,
            "browser_reputation": browser_reputation,
            "proxy_reputation": proxy_reputation,
            "preferred_browser_profile": best_profile,
            "preferred_proxy": best_proxy,
        }

    async def recommend_scrape_strategy(
        self,
        marketplace: str,
        *,
        url: str | None = None,
        window_minutes: int | None = None,
    ) -> dict:
        window = window_minutes or _env_int("ADAPTIVE_BLOCK_WINDOW_MINUTES", 60)
        browser_threshold = _env_int("ADAPTIVE_BROWSER_BLOCK_THRESHOLD", 3)
        browser_failure_threshold = _env_int("ADAPTIVE_BROWSER_FAILURE_THRESHOLD", 3)
        network_threshold = _env_int("ADAPTIVE_NETWORK_ERROR_THRESHOLD", 3)
        health = await self.get_marketplace_health(marketplace, window_minutes=window)
        attempts = await self.get_recent_scrape_attempts(
            marketplace=marketplace,
            limit=_env_int("ADAPTIVE_HEALTH_ATTEMPT_LIMIT", 200),
            minutes=window,
        )
        recent = await self.get_recent_blocked_patterns(
            marketplace=marketplace,
            limit=50,
            minutes=window,
        )

        url_hash = url_to_hash(url) if url else None
        same_url = [event for event in recent if url_hash and event.url_hash == url_hash]
        browser_blocks = [
            event for event in recent
            if event.source == "browser" and event.status == "blocked"
        ]
        browser_failures = [
            event for event in attempts
            if event.source == "browser" and event.status not in {"ok", "skipped"}
        ]
        network_failures = [event for event in recent if event.trigger == "network"]

        if same_url and same_url[0].status == "blocked" and same_url[0].source in {"browser", "strategy"}:
            return {
                "strategy": "defer_same_url",
                "skip": True,
                "skip_browser": True,
                "reason": f"same URL recently blocked by {same_url[0].source}",
                "next_best_strategy": "wait_for_cooldown_or_change_route",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_SAME_URL_COOLDOWN_SEC", 600),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
            }
        if len(browser_failures) >= browser_failure_threshold:
            return {
                "strategy": "api_only_browser_cooldown",
                "skip": False,
                "skip_browser": True,
                "skip_api": False,
                "reason": f"{len(browser_failures)} recent browser failures in {window} min",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_BROWSER_COOLDOWN_SEC", 1200),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "next_best_strategy": "api_or_structured_source_only",
            }
        if len(browser_blocks) >= browser_threshold:
            return {
                "strategy": "api_only_browser_cooldown",
                "skip": False,
                "skip_browser": True,
                "skip_api": False,
                "reason": f"{len(browser_blocks)} recent browser blocks in {window} min",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_BROWSER_COOLDOWN_SEC", 1200),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "next_best_strategy": "api_or_structured_source_only",
            }
        if len(network_failures) >= network_threshold:
            return {
                "strategy": "network_cooldown",
                "skip": True,
                "skip_browser": True,
                "next_best_strategy": "network_cooldown_wait",
                "reason": f"{len(network_failures)} recent network failures in {window} min",
                "cooldown_sec": max(
                    _env_int("ADAPTIVE_NETWORK_COOLDOWN_SEC", 300),
                    health["dynamic_cooldown_sec"],
                ),
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
            }
        if health["disable_api"]:
            return {
                "strategy": "self_heal_disable_api",
                "skip": False,
                "skip_browser": health["avoid_browser"],
                "skip_api": True,
                "reason": f"{health['api_blocks']} recent API blocks in {window} min",
                "next_best_strategy": "browser_if_allowed_or_search_fallback",
                "cooldown_sec": health["dynamic_cooldown_sec"],
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "preferred_browser_profile": health["preferred_browser_profile"],
                "preferred_proxy": health["preferred_proxy"],
            }
        if health["predictive_blocking"]:
            return {
                "strategy": "predictive_heat_cooldown",
                "skip": False,
                "skip_browser": True,
                "reason": f"heat_score={health['heat_score']}",
                "next_best_strategy": "wait_or_use_low_cost_source",
                "cooldown_sec": health["dynamic_cooldown_sec"],
                "heat_score": health["heat_score"],
                "source_scores": health["source_scores"],
                "preferred_browser_profile": health["preferred_browser_profile"],
                "preferred_proxy": health["preferred_proxy"],
            }
        return {
            "strategy": "normal",
            "skip": False,
            "skip_browser": False,
            "skip_api": False,
            "reason": "",
            "next_best_strategy": "reuse_current_strategy",
            "cooldown_sec": 0,
            "heat_score": health["heat_score"],
            "source_scores": health["source_scores"],
            "preferred_browser_profile": health["preferred_browser_profile"],
            "preferred_proxy": health["preferred_proxy"],
        }

    async def add_subscriber(self, user_id: int) -> None:
        from sqlalchemy import select

        async with self.session() as s:
            existing = await s.scalar(select(Subscriber).where(Subscriber.user_id == user_id))
            if not existing:
                s.add(Subscriber(user_id=user_id))
                await s.commit()

    async def remove_subscriber(self, user_id: int) -> None:
        from sqlalchemy import select

        async with self.session() as s:
            existing = await s.scalar(select(Subscriber).where(Subscriber.user_id == user_id))
            if existing:
                await s.delete(existing)
                await s.commit()

    async def get_subscribers(self) -> list[int]:
        from sqlalchemy import select

        async with self.session() as s:
            result = await s.execute(select(Subscriber.user_id).order_by(Subscriber.created_at))
            return list(result.scalars().all())

    async def get_subscriber_count(self) -> int:
        from sqlalchemy import func, select

        async with self.session() as s:
            return await s.scalar(select(func.count(Subscriber.id))) or 0

    async def save_product(self, url: str, data: dict) -> tuple[Product, bool]:
        """
        Сохраняет товар и добавляет запись в историю если цена/наличие изменились.
        Возвращает (product, price_changed).
        """
        from sqlalchemy import desc, select
        from sqlalchemy.exc import IntegrityError

        url_hash = url_to_hash(url)
        now = datetime.now(UTC)

        def _touch_existing(p: Product) -> None:
            p.last_check = now
            p.name = data.get("name", p.name)
            p.image_url = data.get("image_url") or p.image_url

        async with self.session() as s:
            result = await s.execute(select(Product).where(Product.url_hash == url_hash))
            product = result.scalar_one_or_none()

            if not product:
                new_product = Product(
                    url_hash=url_hash,
                    url=url,
                    name=data.get("name"),
                    image_url=data.get("image_url"),
                    first_seen=now,
                    last_check=now,
                )
                s.add(new_product)
                try:
                    await s.flush()
                    product = new_product
                    is_new = True
                except IntegrityError:
                    # A concurrent scrape of the same URL won the insert race
                    # (url_hash UNIQUE). Recover by reusing the row it created
                    # instead of propagating an unhandled exception.
                    await s.rollback()
                    result = await s.execute(select(Product).where(Product.url_hash == url_hash))
                    product = result.scalar_one()
                    _touch_existing(product)
                    is_new = False
            else:
                _touch_existing(product)
                is_new = False

            # Последняя запись истории
            last_result = await s.execute(
                select(PriceHistory)
                .where(PriceHistory.product_id == product.id)
                .order_by(desc(PriceHistory.recorded_at))
                .limit(1)
            )
            last = last_result.scalar_one_or_none()

            new_price = data.get("price")
            # Support both payload key conventions:
            # - "availability" (what parsers/worker currently provide)
            # - "availability_status" (what DB/reporting uses)
            new_status = data.get("availability") or data.get("availability_status") or "out_of_stock"
            price_changed = not last or last.price != new_price or last.availability_status != new_status


            if price_changed:
                s.add(PriceHistory(
                    product_id=product.id,
                    price=new_price,
                    availability_status=new_status,
                    recorded_at=now,
                ))
                if last and not is_new:
                    logger.info(
                        f"Изменение [{product.name}]: "
                        f"{last.price}₽→{new_price}₽ | {last.availability_status}→{new_status}"
                    )
                elif is_new:
                    logger.info(f"Новый товар: {product.name} | {new_price}₽ | {new_status}")

            await s.commit()
            return product, price_changed
