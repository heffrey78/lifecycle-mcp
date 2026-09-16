#!/usr/bin/env python3
"""Short record IDs: what a caller may type instead of the stored ID (roadmap R14).

Stored IDs carry zero padding and a trailing version -- REQ-0012-FUNC-00, TASK-0012-01-00, ADR-0004 -- which are
tedious to type and easy to get wrong. A caller may leave out the padding and the version:

    REQ-12-FUNC   -> REQ-0012-FUNC-00        TASK-12    -> TASK-0012-00-00
    REQ-0012-FUNC -> REQ-0012-FUNC-00        TASK-12-1  -> TASK-0012-01-00
    ADR-4         -> ADR-0004                TDD-4      -> TDD-0004

The type stays in a requirement's alias because numbers repeat across types: REQ-12 alone can be four records
(owner decision, 2026-09-15). Stored IDs are never rewritten; this is only an input form, resolved in one place so
every tool behaves the same. An alias matching nothing, or more than one record, is refused rather than guessed.
"""

import re

# A complete stored ID. These are never treated as aliases: they go to the handler untouched, so "not found" stays
# the handler's answer to give, batch calls still report per ID, and queries still come back empty rather than failing.
STORED_IDS = (
    re.compile(r"^REQ-\d{4}-[A-Z]+-\d{2}$"),
    re.compile(r"^TASK-\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^(?:ADR|TDD)-\d{4}$"),
)

# Table and the column pattern each alias shape has to match, by ID prefix.
ALIAS_PATTERNS = {
    "REQ": re.compile(r"^REQ-(\d+)(?:-([A-Z]+))?(?:-(\d+))?$", re.IGNORECASE),
    "TASK": re.compile(r"^TASK-(\d+)(?:-(\d+))?(?:-(\d+))?$", re.IGNORECASE),
    "ADR": re.compile(r"^ADR-(\d+)$", re.IGNORECASE),
    "TDD": re.compile(r"^TDD-(\d+)$", re.IGNORECASE),
}
PREFIX_TABLES = {"REQ": "requirements", "TASK": "tasks", "ADR": "architecture", "TDD": "architecture"}


def is_stored_id(value: str) -> bool:
    """Whether the value is already a complete stored ID, whether or not such a record exists."""
    return any(pattern.match(value) for pattern in STORED_IDS)


class UnknownAlias(Exception):
    """A short ID matched no record, or matched several; nothing was looked up."""


def candidates(alias: str) -> tuple[str, str] | None:
    """The table and a LIKE pattern matching the stored IDs an alias could mean, or None when it is not an alias."""
    prefix = alias.split("-", 1)[0].upper()
    pattern = ALIAS_PATTERNS.get(prefix)
    if pattern is None:
        return None
    match = pattern.match(alias)
    if match is None:
        return None

    parts = match.groups()
    number = f"{int(parts[0]):04d}"
    if prefix in ("ADR", "TDD"):
        return PREFIX_TABLES[prefix], f"{prefix}-{number}"
    if prefix == "REQ":
        req_type = parts[1].upper() if parts[1] else "%"
        version = f"{int(parts[2]):02d}" if parts[2] else "%"
        return "requirements", f"REQ-{number}-{req_type}-{version}"
    subtask = f"{int(parts[1]):02d}" if parts[1] else "00"
    version = f"{int(parts[2]):02d}" if parts[2] else "%"
    return "tasks", f"TASK-{number}-{subtask}-{version}"


def resolve(db, value: str) -> str:
    """The stored ID a caller meant, or the value unchanged when it is already one (roadmap R14).

    Raises UnknownAlias when the alias matches no record or more than one.
    """
    if not isinstance(value, str) or not value:
        return value

    # A complete stored ID goes through untouched, even when no such record exists: whether it is found, and what
    # that means, is the handler's to say. Only a shortened form is looked up here.
    if is_stored_id(value):
        return value

    guess = candidates(value)
    if guess is None:
        return value
    table, pattern = guess

    rows = db.execute_query(f"SELECT id FROM {table} WHERE id LIKE ? ORDER BY id", [pattern], fetch_all=True) or []
    matches = [row[0] for row in rows]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise UnknownAlias(f"No record matches {value}")
    raise UnknownAlias(f"{value} matches {', '.join(matches)}; say which one")


def resolve_arguments(db, arguments: dict) -> dict:
    """A copy of a tool call's arguments with every record ID resolved (roadmap R14)."""
    resolved = dict(arguments)
    for name, value in arguments.items():
        if not name.endswith(("_id", "_ids")):
            continue
        if isinstance(value, str):
            resolved[name] = resolve(db, value)
        elif isinstance(value, list):
            resolved[name] = [resolve(db, item) for item in value]
    return resolved
