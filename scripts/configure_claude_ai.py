#!/usr/bin/env python3
"""Securely configure Claude API for MarketMind without exposing the key."""
from __future__ import annotations

import getpass
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
MODEL = "claude-sonnet-5-5"


def set_env_value(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    return text.rstrip("\n") + f"\n{line}\n"


def main() -> int:
    if not ENV_FILE.exists():
        print("Не найден .env. Запусти скрипт из установленного проекта MarketMind.")
        return 1

    print("Настройка Claude API для MarketMind.")
    print("Ключ вводится скрыто и не отправляется в чат или журналы.")
    key = getpass.getpass("Вставь Anthropic API key (ввод скрыт): ").strip()
    if not key:
        print("Ключ не введён; настройки не изменены.")
        return 1
    if not key.startswith("sk-ant-"):
        confirm = input("Ключ не начинается с sk-ant-. Всё равно сохранить? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Отменено; настройки не изменены.")
            return 1

    original = ENV_FILE.read_text(encoding="utf-8")
    updated = original
    updated = set_env_value(updated, "AI_PROVIDER", "claude")
    updated = set_env_value(updated, "ANTHROPIC_MODEL", MODEL)
    updated = set_env_value(updated, "ANTHROPIC_API_KEY", key)

    backup = ROOT / f".env.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(ENV_FILE, backup)
    os.chmod(backup, 0o600)

    fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=ROOT, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, ENV_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    print(f"Готово: AI_PROVIDER=claude, модель {MODEL}.")
    print("Ключ сохранён в .env с правами 600; резервная копия .env создана.")
    print("Теперь перезапусти Telegram-бота: systemctl --user restart marketmind-bot.service")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
