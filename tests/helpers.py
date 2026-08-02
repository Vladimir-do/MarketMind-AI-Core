import importlib
import os
import sys


def reload_app_modules(database_url: str | None = None):
    if database_url is not None:
        os.environ["DATABASE_URL"] = database_url

    for name in [
        "app.config",
        "app.database",
        "app.runtime_paths",
        "app.backups.service",
        "app.workspace.files",
        "app.projects.imports",
        "app.projects.service",
        "app.projects.archive",
        "app.effective_card.service",
        "app.exports.service",
        "app.reports.service",
        "app.web.app",
        "app.web.routes.system",
        "app.web.routes.projects",
        "app.content_pipeline.pipeline",
        "app.content_pipeline.jobs",
        "app.content_pipeline.routes",
        "app.competitor_analysis.service",
        "app.competitor_analysis.jobs",
        "app.competitor_analysis.routes",
        "app.exporter",
        "app.reporter",
        "app.agent",
        "app.ai_analyzer",
        "app.ai_client",
    ]:
        if name in sys.modules:
            importlib.reload(sys.modules[name])

    import app.config
    import app.database

    return app.config, app.database
