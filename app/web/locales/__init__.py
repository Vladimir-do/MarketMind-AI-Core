"""Localization support for MarketMind AI web UI."""

from __future__ import annotations

import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent
_cache: dict[str, dict[str, str]] = {}


def load_locale(lang: str = "ru") -> dict[str, str]:
    """Load locale strings from JSON file."""
    if lang in _cache:
        return _cache[lang]
    locale_file = _LOCALES_DIR / f"{lang}.json"
    if locale_file.exists():
        with open(locale_file, encoding="utf-8") as f:
            _cache[lang] = json.load(f)
    else:
        _cache[lang] = {}
    return _cache[lang]


def t(key: str, lang: str = "ru") -> str:
    """Get translated string by key."""
    locale = load_locale(lang)
    return locale.get(key, key)
