from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MARKDOWN_PATH = ROOT / "skills_database.md"
INDEX_PATH = ROOT / "skills_index.json"

ID_RE = re.compile(r"^- ID скилла:\s*`([^`]+)`\s*$", re.MULTILINE)
REQUIRED_FIELDS = {
    "id",
    "title",
    "category",
    "complexity",
    "maturity",
    "priority",
    "dependencies",
    "dependents",
    "source_paths",
}
COMPLEXITIES = {"beginner", "junior", "middle", "senior"}
MATURITIES = {"prototype", "usable", "production-ready"}
PRIORITIES = {"low", "medium", "high", "critical"}


def fail(message: str, errors: list[str]) -> None:
    errors.append(f"ERROR: {message}")


def warn(message: str, warnings: list[str]) -> None:
    warnings.append(f"WARN: {message}")


def load_markdown_ids(errors: list[str]) -> list[str]:
    if not MARKDOWN_PATH.exists():
        fail(f"missing {MARKDOWN_PATH.name}", errors)
        return []
    text = MARKDOWN_PATH.read_text(encoding="utf-8")
    return ID_RE.findall(text)


def load_index(errors: list[str]) -> dict:
    if not INDEX_PATH.exists():
        fail(f"missing {INDEX_PATH.name}", errors)
        return {}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {INDEX_PATH.name}: {exc}", errors)
        return {}


def validate_duplicates(ids: list[str], label: str, errors: list[str]) -> None:
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        fail(f"duplicate skill IDs in {label}: {', '.join(duplicates)}", errors)


def validate_index_shape(index: dict, errors: list[str], warnings: list[str]) -> list[dict]:
    skills = index.get("skills")
    if not isinstance(skills, list):
        fail("skills_index.json must contain a top-level 'skills' list", errors)
        return []

    for skill in skills:
        if not isinstance(skill, dict):
            fail("each skill entry must be an object", errors)
            continue

        skill_id = skill.get("id", "<missing-id>")
        missing = sorted(REQUIRED_FIELDS - set(skill))
        if missing:
            fail(f"{skill_id}: missing required fields: {', '.join(missing)}", errors)

        if skill.get("complexity") not in COMPLEXITIES:
            fail(f"{skill_id}: invalid complexity {skill.get('complexity')!r}", errors)
        if skill.get("maturity") not in MATURITIES:
            fail(f"{skill_id}: invalid maturity {skill.get('maturity')!r}", errors)
        if skill.get("priority") not in PRIORITIES:
            fail(f"{skill_id}: invalid priority {skill.get('priority')!r}", errors)

        for field in ("dependencies", "dependents", "source_paths"):
            if field in skill and not isinstance(skill[field], list):
                fail(f"{skill_id}: {field} must be a list", errors)

        if not skill.get("source_paths"):
            warn(f"{skill_id}: source_paths is empty", warnings)

    return skills


def validate_markdown_json_sync(markdown_ids: list[str], index_ids: list[str], errors: list[str]) -> None:
    markdown_set = set(markdown_ids)
    index_set = set(index_ids)

    only_markdown = sorted(markdown_set - index_set)
    only_index = sorted(index_set - markdown_set)

    if only_markdown:
        fail(f"IDs present in Markdown but missing from JSON: {', '.join(only_markdown)}", errors)
    if only_index:
        fail(f"IDs present in JSON but missing from Markdown: {', '.join(only_index)}", errors)


def validate_dependency_graph(skills: list[dict], errors: list[str], warnings: list[str]) -> None:
    by_id = {skill["id"]: skill for skill in skills if isinstance(skill, dict) and skill.get("id")}
    all_ids = set(by_id)

    for skill in skills:
        skill_id = skill.get("id")
        if not skill_id:
            continue

        dependencies = set(skill.get("dependencies") or [])
        dependents = set(skill.get("dependents") or [])

        unknown_deps = sorted(dependencies - all_ids)
        unknown_dependents = sorted(dependents - all_ids)
        if unknown_deps:
            fail(f"{skill_id}: unknown dependencies: {', '.join(unknown_deps)}", errors)
        if unknown_dependents:
            fail(f"{skill_id}: unknown dependents: {', '.join(unknown_dependents)}", errors)

        for dep_id in dependencies & all_ids:
            reverse = set(by_id[dep_id].get("dependents") or [])
            if skill_id not in reverse:
                warn(f"{skill_id}: dependency {dep_id} does not list {skill_id} as dependent", warnings)

        for dependent_id in dependents & all_ids:
            reverse = set(by_id[dependent_id].get("dependencies") or [])
            if skill_id not in reverse:
                warn(f"{skill_id}: dependent {dependent_id} does not list {skill_id} as dependency", warnings)


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    markdown_ids = load_markdown_ids(errors)
    index = load_index(errors)
    skills = validate_index_shape(index, errors, warnings)
    index_ids = [skill.get("id") for skill in skills if isinstance(skill, dict) and skill.get("id")]

    validate_duplicates(markdown_ids, "skills_database.md", errors)
    validate_duplicates(index_ids, "skills_index.json", errors)
    validate_markdown_json_sync(markdown_ids, index_ids, errors)
    validate_dependency_graph(skills, errors, warnings)

    for message in warnings:
        print(message)
    for message in errors:
        print(message, file=sys.stderr)

    if errors:
        print(f"Validation failed: {len(errors)} error(s), {len(warnings)} warning(s).", file=sys.stderr)
        return 1

    print(
        "Validation passed: "
        f"{len(index_ids)} indexed skill(s), {len(markdown_ids)} markdown skill(s), "
        f"{len(warnings)} warning(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

