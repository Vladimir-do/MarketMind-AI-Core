from datetime import UTC, datetime

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
)
from sqlalchemy.orm import relationship

from app.database.base import Base

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
    availability_status = Column(String(20), nullable=False)  # in_stock / out_of_stock / deleted / blocked / unknown / draft
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
