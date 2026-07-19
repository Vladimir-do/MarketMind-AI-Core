#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "Python не найден. Установите Python 3 или восстановите .venv."
  exit 1
fi

export MARKETMIND_HOME="${MARKETMIND_HOME:-$SCRIPT_DIR/runtime}"
export MARKETMIND_MODE="work"
export MARKETMIND_DATA_DIR="$MARKETMIND_HOME"
export MARKETMIND_WORKSPACE_DIR="$MARKETMIND_HOME"
export DATABASE_URL="sqlite+aiosqlite:///$MARKETMIND_HOME/database/marketmind.db"
export LOG_FILE="$MARKETMIND_HOME/logs/marketmind.log"
export SCRAPE_ATTEMPTS_JSONL="$MARKETMIND_HOME/logs/scrape_attempts.jsonl"
export BLOCK_PATTERNS_JSONL="$MARKETMIND_HOME/logs/blocked_patterns.jsonl"

mkdir -p \
  "$MARKETMIND_HOME/database" \
  "$MARKETMIND_HOME/projects" \
  "$MARKETMIND_HOME/uploads" \
  "$MARKETMIND_HOME/exports" \
  "$MARKETMIND_HOME/reports" \
  "$MARKETMIND_HOME/backups" \
  "$MARKETMIND_HOME/logs"

echo "РАБОЧИЙ РЕЖИМ. ДАННЫЕ СОХРАНЯЮТСЯ"
echo "MARKETMIND_HOME=$MARKETMIND_HOME"
"$PYTHON" -m app.runtime_cli backup-if-needed
echo "Откройте: http://127.0.0.1:18080/projects"
echo "Для безопасной остановки нажмите Ctrl+C в этом терминале."

"$PYTHON" -m uvicorn app.web.app:create_app --factory --host 127.0.0.1 --port 18080
