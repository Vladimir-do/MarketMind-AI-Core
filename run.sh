#!/bin/bash
# Использование:
#   ./run.sh          — запустить бота (по умолчанию)
#   ./run.sh update   — обновить цены существующих товаров

MODE=${1:-bot}

case "$MODE" in
  bot)
    echo "🤖 Запуск Telegram-бота..."
    python -m app.main --telegram
    ;;
  update)
    echo "🔄 Обновление цен..."
    python -m app.main --update
    ;;
  *)
    echo "Использование: ./run.sh [bot|update]"
    exit 1
    ;;
esac
