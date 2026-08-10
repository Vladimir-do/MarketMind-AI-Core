"""Public facade for the app.database package.

Re-exports everything that was importable from the single-file
app/database.py before its decomposition (see docs/STABILIZATION_AUDIT.md
D9): the declarative Base (base.py), the 18 ORM models (models.py),
url_to_hash (utils.py), and the Database class (core.py). Existing call
sites (`from app.database import X`, `import app.database`) are unaffected.
"""

import importlib
import sys

from app.compat.aiosqlite_patch import apply_aiosqlite_future_poll_patch

apply_aiosqlite_future_poll_patch()

# app/database is a package: importlib.reload() on "app.database" (used
# pervasively by tests/helpers.py:reload_app_modules() to rebind Database to
# a fresh DATABASE_URL) only re-executes this __init__.py, not submodules
# already cached in sys.modules. Cascade the reload explicitly so a fresh
# Base/models/Database are rebuilt together on every reload, exactly as when
# this was a single file. Order matters: base before models (models redefine
# their classes against whichever Base object is current at that moment).
for _submodule in (
    "app.database.base",
    "app.database.models",
    "app.database.resilience",
    "app.database.utils",
    "app.database.core",
):
    if _submodule in sys.modules:
        importlib.reload(sys.modules[_submodule])

from app.database.base import Base  # noqa: E402, I001
from app.database.core import Database  # noqa: E402, I001
from app.database.utils import url_to_hash  # noqa: E402, I001
from app.database.models import (  # noqa: E402, I001
    ApprovalRecord,
    BlockedPattern,
    ClientProject,
    ClientProjectFile,
    CompetitorSnapshot,
    ContentPipelineArtifact,
    DomainEventRecord,
    ImportMappingPreset,
    JobRecord,
    PriceHistory,
    Product,
    ProductCardDraft,
    ProductCardVersion,
    ProjectExport,
    ProjectProduct,
    ProjectReport,
    ScrapeAttempt,
    Subscriber,
)

__all__ = [
    "Base",
    "Database",
    "ApprovalRecord",
    "BlockedPattern",
    "ClientProject",
    "ClientProjectFile",
    "CompetitorSnapshot",
    "ContentPipelineArtifact",
    "DomainEventRecord",
    "ImportMappingPreset",
    "JobRecord",
    "PriceHistory",
    "Product",
    "ProductCardDraft",
    "ProductCardVersion",
    "ProjectExport",
    "ProjectProduct",
    "ProjectReport",
    "ScrapeAttempt",
    "Subscriber",
    "url_to_hash",
]
