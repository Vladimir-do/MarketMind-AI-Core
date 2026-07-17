from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue
        from app.database import Database

        db = Database()
        await db.init()
        app.state.db = db
        app.state.ai_queue = DatabaseApprovalQueue(db)
        yield
        await db._engine.dispose()

    app = FastAPI(title="MarketMind AI", version="0.1.0", lifespan=lifespan)

    vendor_dir = STATIC_DIR / "vendor"
    vendor_files = {
        "htmx.min.js": (vendor_dir / "htmx.min.js", "application/javascript; charset=utf-8"),
        "htmx.LICENSE.txt": (vendor_dir / "htmx.LICENSE.txt", "text/plain; charset=utf-8"),
        "htmx.meta.json": (vendor_dir / "htmx.meta.json", "application/json; charset=utf-8"),
    }

    @app.get("/static/vendor/{filename}")
    async def vendor_static(filename: str) -> Response:
        file_info = vendor_files.get(filename)
        if file_info is None:
            raise HTTPException(status_code=404, detail="Файл не найден")
        file_path, media_type = file_info
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Файл не найден")
        if file_path.suffix == ".js":
            return Response(file_path.read_text(encoding="utf-8"), media_type=media_type)
        return Response(file_path.read_bytes(), media_type=media_type)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from app.analytics.routes import router as analytics_router
    from app.web.routes.dashboard import router as dashboard_router
    from app.web.routes.editor import router as editor_router
    from app.web.routes.import_ import router as import_router
    from app.web.routes.product_detail import router as product_detail_router
    from app.web.routes.products import router as products_router
    from app.web.routes.projects import router as projects_router
    from app.web.routes.reports import router as reports_router
    from app.web.routes.suggestions import router as suggestions_router

    app.include_router(dashboard_router)
    app.include_router(products_router)
    app.include_router(import_router)
    app.include_router(projects_router)
    app.include_router(suggestions_router)
    app.include_router(product_detail_router)
    app.include_router(editor_router)
    app.include_router(analytics_router)
    app.include_router(reports_router)

    return app
