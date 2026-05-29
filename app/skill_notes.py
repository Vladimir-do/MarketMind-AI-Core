from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml


SESSION_UPDATES_DIR = Path(__file__).resolve().parent.parent / "project_skills" / "session_updates"


@dataclass(frozen=True, slots=True)
class SkillProposal:
    path: Path
    proposed_id: str


def create_skill_note_proposal(
    note: str,
    *,
    source: str = "telegram",
    root: Path = SESSION_UPDATES_DIR,
) -> SkillProposal:
    clean_note = _sanitize_note(note)
    if not clean_note:
        raise ValueError("Skill note is empty.")

    now = datetime.now()
    proposed_id = _proposed_id(clean_note)
    filename = f"{now:%Y-%m-%d-%H%M%S}-{proposed_id}.yaml"
    root.mkdir(parents=True, exist_ok=True)
    path = root / filename

    payload = {
        "schema_version": "1.0",
        "created_at": now.strftime("%Y-%m-%d"),
        "session_summary": f"Pending skill note from {source}: {clean_note[:120]}",
        "status": "pending",
        "candidate_skills": [
            {
                "proposed_id": proposed_id,
                "title": _title_from_note(clean_note),
                "category": "architecture",
                "maturity": "prototype",
                "priority": "medium",
                "source_context": {
                    "files": [],
                    "commands": [],
                    "conversation_notes": [clean_note],
                },
                "why_reusable": "Captured from Telegram as a potentially reusable project lesson.",
                "suggested_dependencies": [],
                "suggested_dependents": [],
                "snippet": "",
                "open_questions": ["Review and merge into the main skillpack if reusable."],
            }
        ],
        "existing_skill_updates": [],
        "missing_skill_updates": [],
        "security_notes": {
            "contains_secrets": False,
            "redactions": [],
        },
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return SkillProposal(path=path, proposed_id=proposed_id)


def list_pending_skill_proposals(*, root: Path = SESSION_UPDATES_DIR, limit: int = 10) -> list[Path]:
    if not root.exists():
        return []
    paths = sorted(root.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True)
    return paths[: max(1, limit)]


def _sanitize_note(note: str) -> str:
    text = re.sub(r"https?://\S+", "[url-redacted]", note or "")
    text = re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b", "[telegram-token-redacted]", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    return re.sub(r"\s+", " ", text).strip()


def _proposed_id(note: str) -> str:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", note.lower())
    useful = [word for word in words if len(word) >= 3][:6]
    slug = "-".join(useful) or "telegram-skill-note"
    slug = re.sub(r"[^a-zа-яё0-9-]+", "-", slug).strip("-")
    return slug[:80] or "telegram-skill-note"


def _title_from_note(note: str) -> str:
    title = note.strip()
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title or "Telegram skill note"
