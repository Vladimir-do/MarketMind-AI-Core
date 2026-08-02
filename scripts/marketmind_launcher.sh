#!/usr/bin/env bash
set -euo pipefail

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

mkdir -p "$MARKETMIND_HOME"/{database,projects,uploads,exports,reports,backups,logs}

pause() {
  echo
  read -r -p "Нажми Enter, чтобы вернуться в меню..."
}

run_planned() { "$ROOT_DIR/scripts/planned_marketmind_run.sh"; }

run_web() {
  local port="${MARKETMIND_WEB_PORT:-8000}"
  echo "Веб-интерфейс: http://127.0.0.1:$port"
  echo "Остановка: Ctrl+C"
  "$PYTHON_BIN" -m app.main --web --host 127.0.0.1 --port "$port"
}

run_metrics() { "$PYTHON_BIN" -m app.main --metrics "${MARKETMIND_METRICS_LIMIT:-20}"; }
run_blocks() { "$PYTHON_BIN" -m app.main --blocks "${MARKETMIND_BLOCKS_LIMIT:-20}"; }
run_ozon_login() { "$PYTHON_BIN" -m app.main --ozon-login; }

while true; do
  clear
  cat <<MENU
MarketMind AI Launcher

Проект: $ROOT_DIR
Python: $PYTHON_BIN
Runtime: $MARKETMIND_HOME
Database: $DATABASE_URL

1. Плановый запуск: обновление + отчёт + диагностика
2. Открыть веб-интерфейс
3. Показать последние метрики парсинга
4. Показать последние блокировки
5. Ozon login / сохранить браузерный профиль
0. Выход
MENU
  read -r -p "Выбери пункт: " choice
  echo
  case "$choice" in
    1) run_planned; pause ;;
    2) run_web; pause ;;
    3) run_metrics; pause ;;
    4) run_blocks; pause ;;
    5) run_ozon_login; pause ;;
    0) exit 0 ;;
    *) echo "Неизвестный пункт: $choice"; pause ;;
  esac
done
