"""Prepare an isolated L1 manual acceptance demo workspace."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


async def _create_demo_project(database_url: str, data_dir: Path, workspace_dir: Path) -> str:
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


def main() -> None:
    root = _repo_root()
    if root.as_posix() not in sys.path:
        sys.path.insert(0, root.as_posix())
    demo_root = Path(tempfile.gettempdir()) / "marketmind_l1_acceptance_demo"
    data_dir = demo_root / "data"
    workspace_dir = demo_root / "workspace"
    demo_root.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    fixture = root / "tests" / "fixtures" / "l1_demo_products.csv"
    demo_csv = demo_root / "l1_demo_products.csv"
    shutil.copyfile(fixture, demo_csv)

    db_path = demo_root / "marketmind_l1_demo.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    project_id = asyncio.run(_create_demo_project(database_url, data_dir, workspace_dir))

    print("Демонстрационная среда L1.1 подготовлена.")
    print(f"Проект: {project_id}")
    print(f"Файл для загрузки: {demo_csv}")
    print("Команда запуска:")
    print(
        " ".join(
            [
                f"DATABASE_URL={database_url}",
                f"MARKETMIND_DATA_DIR={data_dir.as_posix()}",
                f"MARKETMIND_WORKSPACE_DIR={workspace_dir.as_posix()}",
                f"SCRAPE_ATTEMPTS_JSONL={(data_dir / 'scrape_attempts.jsonl').as_posix()}",
                f"BLOCK_PATTERNS_JSONL={(data_dir / 'block_patterns.jsonl').as_posix()}",
                ".venv/bin/python -m uvicorn app.web.app:create_app",
                "--factory --host 127.0.0.1 --port 18080",
            ]
        )
    )
    print("Адрес интерфейса: http://127.0.0.1:18080/projects")
    print("Сценарий ручной проверки описан в docs/L1_MANUAL_ACCEPTANCE.md")


if __name__ == "__main__":
    main()
