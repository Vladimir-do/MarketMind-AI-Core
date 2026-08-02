#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${MARKETMIND_PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

export MARKETMIND_HOME="${MARKETMIND_HOME:-$ROOT_DIR/runtime}"
export MARKETMIND_DATA_DIR="${MARKETMIND_DATA_DIR:-$MARKETMIND_HOME}"
export MARKETMIND_WORKSPACE_DIR="${MARKETMIND_WORKSPACE_DIR:-$MARKETMIND_HOME/projects}"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$MARKETMIND_HOME/database/marketmind.db}"
export LOG_FILE="${LOG_FILE:-$MARKETMIND_HOME/logs/marketmind.log}"
export SCRAPE_ATTEMPTS_JSONL="${SCRAPE_ATTEMPTS_JSONL:-$MARKETMIND_HOME/logs/scrape_attempts.jsonl}"
export BLOCK_PATTERNS_JSONL="${BLOCK_PATTERNS_JSONL:-$MARKETMIND_HOME/logs/blocked_patterns.jsonl}"
export OZON_SKIP_BROWSER_AFTER_API_BLOCK="${OZON_SKIP_BROWSER_AFTER_API_BLOCK:-1}"

LOG_DIR="${MARKETMIND_SCHEDULE_LOG_DIR:-$MARKETMIND_HOME/logs/scheduled}"
mkdir -p "$MARKETMIND_HOME"/{database,projects,uploads,exports,reports,backups,logs} "$LOG_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
RUN_LOG="$LOG_DIR/planned_run_$STAMP.log"
FAILED_STAGES=()

run_stage() {
  local title="$1"
  shift
  echo "== $title =="
  if "$@"; then
    echo "STATUS: OK"
  else
    local code=$?
    echo "STATUS: FAILED (exit=$code)"
    FAILED_STAGES+=("$title:$code")
  fi
  echo
}

{
  echo "MarketMind planned run started: $(date -Is)"
  echo "Root: $ROOT_DIR"
  echo "Python: $PYTHON_BIN"
  echo "Runtime: $MARKETMIND_HOME"
  echo "Database: $DATABASE_URL"
  echo

  run_stage "Backup" "$PYTHON_BIN" -m app.runtime_cli backup-if-needed
  run_stage "Update products" "$PYTHON_BIN" -m app.main --update
  run_stage "Generate report" "$PYTHON_BIN" -m app.main --report
  run_stage "Recent metrics" "$PYTHON_BIN" -m app.main --metrics 20
  run_stage "Recent blocks" "$PYTHON_BIN" -m app.main --blocks 20

  echo "MarketMind planned run finished: $(date -Is)"
  if ((${#FAILED_STAGES[@]})); then
    echo "RESULT: FAILED"
    printf 'Failed stage: %s\n' "${FAILED_STAGES[@]}"
  else
    echo "RESULT: OK"
  fi
} 2>&1 | tee "$RUN_LOG"

if ((${#FAILED_STAGES[@]})); then
  echo "Run completed with errors. Log: $RUN_LOG"
  exit 1
fi

echo "Run completed successfully. Log: $RUN_LOG"
