"""Rules engine — loads YAML rules and does pre-match filtering."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Optional

import yaml

from deskmind.models.schemas import (
    ActionType,
    FileInfo,
    OrganizeAction,
    Rule,
)


def _parse_age(age_str: Optional[str]) -> Optional[tuple[str, int]]:
    """Parse age string like '30d', '3m', '90d' into days. Returns None if invalid."""
    if not age_str:
        return None
    match = re.match(r"^([<>=]+)?\s*(\d+)\s*([dDmM])?$", age_str.strip())
    if not match:
        return None
    op = match.group(1) or "<"
    value = int(match.group(2))
    unit = match.group(3)
    if unit and unit.lower() == "m":
        value *= 30
    return (op, value)


def _file_age_days(info: FileInfo) -> int:
    import datetime
    from datetime import timezone
    now = datetime.datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - info.modified_at).days


def _matches_glob(name: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _check_age_condition(info: FileInfo, age_str: str) -> bool:
    parsed = _parse_age(age_str)
    if parsed is None:
        return True
    op, target = parsed
    age = _file_age_days(info)
    if op == ">" or op == ">=":
        return age >= target if "=" in op else age > target
    elif op == "<" or op == "<=":
        return age <= target if "=" in op else age < target
    elif op == "=":
        return age == target
    return True


def load_rules_from_yaml(path: Path) -> list[Rule]:
    """Load structured rules from a YAML file."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "rules" not in data:
        return []
    rules = []
    for item in data["rules"]:
        action_str = item.get("action", "move")
        rules.append(Rule(
            name=item.get("name", ""),
            folder=item.get("folder", ""),
            description=item.get("description", ""),
            include=item.get("include", []),
            exclude=item.get("exclude", []),
            age=item.get("age"),
            action=ActionType(action_str),
            natural_language=item.get("natural_language", ""),
        ))
    return rules


def pre_match_files(
    files: list[FileInfo],
    rules: list[Rule],
) -> tuple[list[OrganizeAction], list[FileInfo]]:
    """Pre-match files against structured rules with explicit include patterns.

    Returns (prematched_actions, remaining_files).
    """
    actions: list[OrganizeAction] = []
    remaining: list[FileInfo] = []
    matched_indices: set[int] = set()

    for rule in rules:
        if not rule.include:
            continue

        for i, f in enumerate(files):
            if i in matched_indices:
                continue

            if rule.age and not _check_age_condition(f, rule.age):
                continue

            if not _matches_glob(f.name, rule.include):
                continue

            if rule.exclude and _matches_glob(f.name, rule.exclude):
                continue

            matched_indices.add(i)
            actions.append(OrganizeAction(
                file_path=f.path,
                action=rule.action,
                target_folder=rule.folder,
                reason=rule.description or f"Matched rule: {rule.name}",
            ))

    for i, f in enumerate(files):
        if i not in matched_indices:
            remaining.append(f)

    return actions, remaining


def build_llm_rule_text(
    rules: list[Rule],
    natural_language_override: str = "",
) -> str:
    """Build a rule text block to send to the LLM as context.

    Structured rules are included as reference, and the natural language
    rule (or override) serves as the primary instruction.
    """
    parts: list[str] = []

    nl_rule = natural_language_override
    if not nl_rule:
        nl_parts = [r.natural_language for r in rules if r.natural_language]
        if nl_parts:
            nl_rule = " ".join(nl_parts)

    if nl_rule:
        parts.append(f"## User's instruction\n{nl_rule}\n")
    else:
        parts.append("## User's instruction\nOrganize my desktop files neatly by their type and purpose.\n")

    structured = [r for r in rules if r.include]
    if structured:
        parts.append("## Structured rules (reference)")
        for r in structured:
            line = f"- {r.name or '(unnamed)'}"
            if r.folder:
                line += f" → {r.folder}"
            if r.include:
                line += f" [patterns: {', '.join(r.include)}]"
            if r.age:
                line += f" [age: {r.age}]"
            parts.append(line)

    return "\n".join(parts)
