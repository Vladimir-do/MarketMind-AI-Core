"""Cross-platform launcher for MarketMind AI L1.1 manual acceptance demo."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 18080


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _prepare_paths(root: Path) -> tuple[Path, Path, Path, Path]:
    demo_root = Path(tempfile.gettempdir()) / "marketmind_l1_acceptance_demo"
    data_dir = demo_root / "data"
    workspace_dir = demo_root / "workspace"
    data_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    fixture = root / "tests" / "fixtures" / "l1_demo_products.csv"
    demo_csv = demo_root / "l1_demo_products.csv"
    shutil.copyfile(fixture, demo_csv)
    db_path = demo_root / "marketmind_l1_demo.db"
    return data_dir, workspace_dir, demo_csv, db_path


async def _ensure_demo_project(database_url: str, data_dir: Path, workspace_dir: Path) -> str:
    os.environ["DATABASE_URL"] = database_url
    os.environ["MARKETMIND_DATA_DIR"] = data_dir.as_posix()
    os.environ["MARKETMIND_WORKSPACE_DIR"] = workspace_dir.as_posix()
    os.environ["SCRAPE_ATTEMPTS_JSONL"] = (data_dir / "scrape_attempts.jsonl").as_posix()
    os.environ["BLOCK_PATTERNS_JSONL"] = (data_dir / "block_patterns.jsonl").as_posix()

    from app.database import Database
    from app.projects.service import ProjectService

    db = Database()
    await db.init()
    try:
        project = await ProjectService(db).create_project(
            name="Демонстрационный заказ L1.1",
            client_name="Учебный заказчик",
            marketplace="ozon",
            description="Безопасный синтетический проект для ручной приёмки L1.1.",
        )
        return project.project_id
    finally:
        await db._engine.dispose()


def _open_browser_later(url: str) -> None:
    time.sleep(2.0)
    webbrowser.open(url)


def main() -> None:
    root = _repo_root()
    if root.as_posix() not in sys.path:
        sys.path.insert(0, root.as_posix())

    data_dir, workspace_dir, demo_csv, db_path = _prepare_paths(root)
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    project_id = asyncio.run(_ensure_demo_project(database_url, data_dir, workspace_dir))
    url = f"http://{HOST}:{PORT}/projects"

    print("MarketMind AI L1.1 demo готов.")
    print(f"Проект: {project_id}")
    print(f"Файл для загрузки: {demo_csv}")
    print(f"Откройте: {url}")
    print("Для остановки нажмите Ctrl+C.")

    threading.Thread(target=_open_browser_later, args=(url,), daemon=True).start()

    import uvicorn

    uvicorn.run("app.web.app:create_app", factory=True, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
