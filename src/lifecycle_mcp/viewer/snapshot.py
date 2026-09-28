"""Read a tracker into memory without touching it (REQ-0006-INTF-00, TASK-0090).

The reason this reads through SQLite rather than copying the file: the server runs with journal_mode=WAL, so a copy of
lifecycle.db holds only what has been checkpointed. Measured on 2026-09-28, the repository's own main database file was
six days behind its -wal - a whole session's work existed nowhere else. Opening the database and asking SQLite for the
rows sees the WAL, takes a consistent read snapshot, and needs no checkpoint, no shutdown and no cooperation from the
process writing to it.

immutable=1 would be the tempting flag here and is exactly wrong: it tells SQLite the file cannot change, so the WAL is
ignored and the stale read comes back. mode=ro is the one that means read-only.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..handlers.architecture_handler import ARCHITECTURE_JSON_FIELDS
from ..handlers.requirement_handler import REQUIREMENT_JSON_FIELDS
from ..handlers.task_handler import TASK_JSON_FIELDS

# The stored columns holding JSON, by table, taken from the handlers rather than listed again: a viewer that parsed a
# different set of columns than get_details would show a record differently from the tool that owns it.
JSON_FIELDS: dict[str, tuple[str, ...]] = {
    "requirements": tuple(REQUIREMENT_JSON_FIELDS),
    "tasks": tuple(TASK_JSON_FIELDS),
    "architecture": tuple(ARCHITECTURE_JSON_FIELDS),
}

# Ordered by primary key so two snapshots of an unchanged database are identical: the page's own content should differ
# only when the tracker did.
TABLE_ORDER: dict[str, str] = {
    "requirements": "id",
    "tasks": "id",
    "architecture": "id",
    "relationships": "id",
    "reviews": "id",
    "lifecycle_events": "id",
    "schema_version": "version",
}


@dataclass
class Snapshot:
    """Every row the viewer shows, with JSON columns already parsed."""

    database_path: str
    requirements: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    architecture: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    schema_version: list[dict[str, Any]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Row counts by kind, for a restore or a render to check itself against."""
        return {
            "requirements": len(self.requirements),
            "tasks": len(self.tasks),
            "architecture": len(self.architecture),
            "relationships": len(self.relationships),
            "comments": len(self.comments),
            "events": len(self.events),
        }


def read_only_uri(db_path: str | Path) -> str:
    """The URI that reads a live database without writing to it or missing its WAL."""
    return f"{Path(db_path).resolve().as_uri()}?mode=ro"


def _parse_json_columns(row: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """Parse the stored JSON columns, leaving a malformed value as None rather than dropping the row.

    The handlers fall back to [] and log; here a value that will not parse is reported as missing, so a reader sees
    that the field could not be read instead of an empty list that looks like a field nobody filled in.
    """
    for column in columns:
        stored = row.get(column)
        if not stored:
            row[column] = None
            continue
        if isinstance(stored, str):
            try:
                row[column] = json.loads(stored)
            except (json.JSONDecodeError, TypeError):
                row[column] = None
    return row


def read_snapshot(db_path: str | Path) -> Snapshot:
    """Every row the viewer needs, read from a database that may be in use.

    Raises sqlite3.OperationalError if the file is not a readable tracker; the caller reports that rather than
    rendering an empty page that looks like an empty project.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"No tracker database at {path}")

    connection = sqlite3.connect(read_only_uri(path), uri=True, timeout=30.0)
    try:
        connection.row_factory = sqlite3.Row
        # One read transaction for the whole snapshot, so the tables cannot be read either side of someone else's
        # write and disagree with each other. WAL means this neither blocks the writer nor is blocked by it.
        connection.execute("BEGIN")
        rows: dict[str, list[dict[str, Any]]] = {}
        for table, order_by in TABLE_ORDER.items():
            cursor = connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}")  # noqa: S608 (fixed names above)
            rows[table] = [_parse_json_columns(dict(row), JSON_FIELDS.get(table, ())) for row in cursor.fetchall()]
        connection.execute("COMMIT")
    finally:
        connection.close()

    return Snapshot(
        database_path=str(path),
        requirements=rows["requirements"],
        tasks=rows["tasks"],
        architecture=rows["architecture"],
        relationships=rows["relationships"],
        comments=rows["reviews"],
        events=rows["lifecycle_events"],
        schema_version=rows["schema_version"],
    )
