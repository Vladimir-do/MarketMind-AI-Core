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
  read -r -p "Нажмите Enter для выхода..."
  exit 1
fi

echo "Запускаю MarketMind AI L1.1 demo..."
"$PYTHON" START_L1_DEMO.py
