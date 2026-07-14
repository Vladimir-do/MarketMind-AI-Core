"""Project defragmentation audit.

The script reports code hotspots and runtime clutter without deleting files.
Use it before cleanup/refactor passes to keep the project layout measurable.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "venv",
}

RUNTIME_PATHS = (
    ".ozon_profile",
    "app/data",
    "app/data/debug",
    "app/data/scrapes",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
)

SOURCE_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json"}
LOOSE_ARTIFACT_SUFFIXES = {
    ".csv",
    ".db",
    ".html",
    ".jsonl",
    ".log",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".xlsx",
}


@dataclass(frozen=True)
class FileInfo:
    path: str
    bytes: int
    lines: int | None = None


@dataclass(frozen=True)
class DirInfo:
    path: str
    bytes: int
    files: int


@dataclass(frozen=True)
class DefragReport:
    root: str
    source_files: int
    source_bytes: int
    largest_python: list[FileInfo]
    runtime_dirs: list[DirInfo]
    loose_artifacts: list[FileInfo]
    duplicate_envs: list[str]


def _is_skipped(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(part in SKIP_DIRS for part in rel_parts)


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _line_count(path: Path) -> int | None:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return None


def _dir_info(path: Path, root: Path) -> DirInfo:
    total = 0
    files = 0
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                total += _safe_size(item)
    return DirInfo(path=path.relative_to(root).as_posix(), bytes=total, files=files)


def _format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def build_report(root: Path, limit: int = 15) -> DefragReport:
    root = root.resolve()
    source_files: list[Path] = []
    python_files: list[Path] = []
    loose_artifacts: list[FileInfo] = []

    for path in root.rglob("*"):
        if not path.is_file() or _is_skipped(path, root):
            continue
        rel = path.relative_to(root)
        if path.suffix.lower() in SOURCE_SUFFIXES:
            source_files.append(path)
        if path.suffix.lower() == ".py":
            python_files.append(path)
        if len(rel.parts) == 1 and path.suffix.lower() in LOOSE_ARTIFACT_SUFFIXES:
            loose_artifacts.append(FileInfo(rel.as_posix(), _safe_size(path)))

    largest_python = [
        FileInfo(
            path=path.relative_to(root).as_posix(),
            bytes=_safe_size(path),
            lines=_line_count(path),
        )
        for path in sorted(python_files, key=_safe_size, reverse=True)[:limit]
    ]

    runtime_dirs = [
        _dir_info(root / item, root)
        for item in RUNTIME_PATHS
        if (root / item).exists()
    ]
    runtime_dirs.sort(key=lambda item: item.bytes, reverse=True)

    duplicate_envs = [
        item
        for item in (".venv", "venv")
        if (root / item).exists()
    ]

    return DefragReport(
        root=root.as_posix(),
        source_files=len(source_files),
        source_bytes=sum(_safe_size(path) for path in source_files),
        largest_python=largest_python,
        runtime_dirs=runtime_dirs,
        loose_artifacts=sorted(loose_artifacts, key=lambda item: item.bytes, reverse=True)[:limit],
        duplicate_envs=duplicate_envs if len(duplicate_envs) > 1 else [],
    )


def print_report(report: DefragReport) -> None:
    print(f"Project root: {report.root}")
    print(f"Source files: {report.source_files} ({_format_bytes(report.source_bytes)})")

    if report.duplicate_envs:
        print("\nDuplicate virtualenvs:")
        for path in report.duplicate_envs:
            print(f"  - {path}")

    print("\nLargest Python modules:")
    for item in report.largest_python:
        line_text = f", {item.lines} lines" if item.lines is not None else ""
        print(f"  - {item.path}: {_format_bytes(item.bytes)}{line_text}")

    print("\nRuntime/cache directories:")
    for item in report.runtime_dirs:
        print(f"  - {item.path}: {_format_bytes(item.bytes)}, files={item.files}")

    if report.loose_artifacts:
        print("\nLoose top-level artifacts:")
        for item in report.loose_artifacts:
            print(f"  - {item.path}: {_format_bytes(item.bytes)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit project fragmentation and runtime clutter.")
    parser.add_argument("--root", default=".", help="Project root to inspect.")
    parser.add_argument("--limit", type=int, default=15, help="Number of large files to show.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    report = build_report(Path(args.root), limit=max(1, args.limit))
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
