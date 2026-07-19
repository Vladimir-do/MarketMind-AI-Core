"""Small launcher helpers for local runtime scripts."""

from __future__ import annotations

import argparse

from app.backups.service import create_backup_if_database_exists
from app.runtime_paths import ensure_runtime_layout, runtime_layout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "backup-if-needed"])
    args = parser.parse_args()
    layout = ensure_runtime_layout()
    if args.command == "init":
        print(f"MARKETMIND_HOME={layout.home}")
        return
    backup = create_backup_if_database_exists(reason="startup")
    if backup:
        print(f"DB backup: {backup['path']}")
    else:
        print(f"DB backup: skipped, no database at {runtime_layout().database_dir}")


if __name__ == "__main__":
    main()
