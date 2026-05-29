import importlib
import os
import sys


def reload_app_modules(database_url: str | None = None):
    if database_url is not None:
        os.environ["DATABASE_URL"] = database_url

    for name in [
        "app.config",
        "app.database",
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

