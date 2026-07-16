from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.database import Database
        from app.ai_recommendation.db_approval import DatabaseApprovalQueue

        db = Database()
        await db.init()
        app.state.db = db
        app.state.ai_queue = DatabaseApprovalQueue(db)
        yield
        await db._engine.dispose()

    app = FastAPI(title="MarketMind AI", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    from app.web.routes.dashboard import router as dashboard_router
    from app.web.routes.products import router as products_router
    from app.web.routes.import_ import router as import_router
    from app.web.routes.suggestions import router as suggestions_router
    from app.web.routes.product_detail import router as product_detail_router
    from app.analytics.routes import router as analytics_router
    from app.web.routes.reports import router as reports_router

    app.include_router(dashboard_router)
    app.include_router(products_router)
    app.include_router(import_router)
    app.include_router(suggestions_router)
    app.include_router(product_detail_router)
    app.include_router(analytics_router)
    app.include_router(reports_router)

    return app
