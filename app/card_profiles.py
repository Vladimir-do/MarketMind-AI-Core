from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
DEFAULT_PROFILE_NAME = "default"


@dataclass(slots=True)
class CardProfile:
    name: str
    language: str = "ru"
    tone_voice: str = "professional"
    max_length: int = 1500
    forbidden_words: list[str] = None
    required_attributes: list[str] = None

    def __post_init__(self) -> None:
        self.language = (self.language or "ru").lower()
        self.tone_voice = (self.tone_voice or "professional").lower()
        self.max_length = int(self.max_length or 1500)
        self.forbidden_words = [str(x).strip().lower() for x in (self.forbidden_words or []) if str(x).strip()]
        self.required_attributes = [str(x).strip() for x in (self.required_attributes or []) if str(x).strip()]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "language": self.language,
            "tone_voice": self.tone_voice,
            "max_length": self.max_length,
            "forbidden_words": self.forbidden_words,
            "required_attributes": self.required_attributes,
        }


def ensure_profiles_dir() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def list_profiles() -> list[str]:
    ensure_profiles_dir()
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml"))


def load_profile(name: str | None) -> CardProfile:
    ensure_profiles_dir()
    profile_name = (name or DEFAULT_PROFILE_NAME).strip().lower()
    path = PROFILES_DIR / f"{profile_name}.yaml"
    if not path.exists():
        path = PROFILES_DIR / f"{DEFAULT_PROFILE_NAME}.yaml"
        profile_name = DEFAULT_PROFILE_NAME
    data = _load_yaml(path)
    return CardProfile(
        name=profile_name,
        language=data.get("language", "ru"),
        tone_voice=data.get("tone_voice", "professional"),
        max_length=data.get("max_length", 1500),
        forbidden_words=data.get("forbidden_words", []),
        required_attributes=data.get("required_attributes", []),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw if isinstance(raw, dict) else {}
