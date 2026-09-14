#!/usr/bin/env python3
"""
Base Handler class for MCP Lifecycle Management Server
Provides common functionality for all domain handlers
"""

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from mcp.types import TextContent

from ..database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class ErrorResult(list):
    """Content for a failed tool call. The server reports it to the client with isError=true."""


class RevisionConflict(Exception):
    """An edit named an if_revision that is no longer current; nothing was written."""

    def __init__(self, entity_id: str, current: int, expected: int):
        super().__init__(f"{entity_id} is at revision {current}, not {expected}. Reload it and retry.")
        self.current = current


class DeleteRefused(Exception):
    """A delete was refused because the record is past its early stage or other records depend on it."""


class EditRefused(Exception):
    """An edit was refused by a lifecycle rule (a missing reason, a decided ADR, a cycle); nothing was written."""


# Inputs every update tool accepts next to the fields it edits.
EDIT_OPTION_PROPERTIES = {
    "reason": {"type": "string", "description": "Why the change is made; shown in get_entity_history"},
    "actor": {"type": "string", "description": "Who makes the change (default: MCP User)"},
    "if_revision": {"type": "integer", "description": "Apply the edit only if the record is still at this revision"},
}


@dataclass
class EditResult:
    """Outcome of BaseHandler._apply_edit."""

    changed: list[str]  # fields whose stored value changed, in the order given
    revision: int  # the record's revision after the edit
    before: dict[str, Any]  # the record as it was before the edit


class BaseHandler(ABC):
    """Abstract base class for all MCP tool handlers"""

    def __init__(self, db_manager: DatabaseManager):
        """Initialize handler with database manager"""
        self.db = db_manager
        self.logger = logger.getChild(self.__class__.__name__)

    def _create_response(self, text: str) -> list[TextContent]:
        """Create standardized response format"""
        return [TextContent(type="text", text=text)]

    def _create_above_fold_response(
        self, status: str, key_info: str, action_info: str = "", details: str = ""
    ) -> list[TextContent]:
        """Create above-the-fold optimized response format

        Args:
            status: Status indicator (SUCCESS/ERROR/INFO etc)
            key_info: Most important information (ID, count, etc)
            action_info: Actionable information or next steps (optional)
            details: Detailed information for expansion (optional)
        """
        # Line 1: Status + Key Info
        line1 = f"[{status}] {key_info}"

        # Line 2: Action info if provided
        line2 = action_info if action_info else ""

        # Line 3: Summary or continuation indicator
        line3 = "📄 Details available below (expand to view)" if details else ""

        # Build response
        response_lines = [line1]
        if line2:
            response_lines.append(line2)
        if line3:
            response_lines.append(line3)

        # Add details section if provided
        if details:
            response_lines.append("")  # Blank line separator
            response_lines.append(details)

        return [TextContent(type="text", text="\n".join(response_lines))]

    def _format_status_summary(self, entity_type: str, entity_id: str, status: str, extra_info: str = "") -> str:
        """Format a concise status summary for above-the-fold display"""
        base = f"{entity_type} {entity_id} [{status}]"
        if extra_info:
            return f"{base} - {extra_info}"
        return base

    def _format_count_summary(self, entity_type: str, count: int, filter_desc: str = "") -> str:
        """Format a count summary for above-the-fold display"""
        if filter_desc:
            return f"Found {count} {entity_type}(s) matching: {filter_desc}"
        return f"Found {count} {entity_type}(s)"

    def _create_error_response(self, error_msg: str, exception: Exception | None = None) -> list[TextContent]:
        """Create standardized error response; the exception's message is included so agents can act on it"""
        if exception:
            error_msg = f"{error_msg}: {exception}"
        self.logger.error(error_msg)

        # Use above-the-fold format for errors
        return ErrorResult(self._create_above_fold_response("ERROR", error_msg))

    def _validate_required_params(self, params: dict[str, Any], required_fields: list[str]) -> str | None:
        """Validate that required parameters are present"""
        missing = [field for field in required_fields if field not in params or params[field] is None]
        if missing:
            return f"Missing required parameters: {', '.join(missing)}"
        return None

    def _safe_json_loads(self, json_str: str | None, default: Any = None) -> Any:
        """Safely load JSON string with fallback"""
        if not json_str:
            return default or []
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"Failed to parse JSON: {json_str}")
            return default or []

    def _format_json_field(self, stored: str | None) -> str:
        """Markdown bullet lines for a stored JSON list (or object); "" when the field is empty"""
        value = self._safe_json_loads(stored)
        if isinstance(value, dict):
            return "".join(f"- **{key}**: {item}\n" for key, item in value.items())
        if isinstance(value, list):
            return "".join(f"- {item}\n" for item in value)
        return f"{value}\n" if value else ""

    def _format_sections(self, record: Any, sections: Iterable[tuple[str, str]], template: str) -> str:
        """Render each non-empty (column, title) JSON list field of a record with template ({title}, {body})"""
        text = ""
        for column, title in sections:
            body = self._format_json_field(record[column])
            if body:
                text += template.format(title=title, body=body)
        return text

    def _safe_json_dumps(self, data: Any) -> str:
        """Safely dump data to JSON string"""
        try:
            return json.dumps(data) if data is not None else "[]"
        except (TypeError, ValueError) as e:
            self.logger.warning(f"Failed to serialize to JSON: {str(e)}")
            return "[]"

    def _link(
        self,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relationship_type: str,
        *,
        cursor: sqlite3.Cursor | None = None,
    ):
        """Record a link in the relationships table, the only place links are stored (idempotent).

        Direction conventions: requirement -> task (implements), requirement -> architecture (addresses),
        child -> parent (parent), dependent -> dependency (depends/requires/informs), blocker -> blocked (blocks).
        Pass cursor to write inside an open transaction.
        """
        sql = (
            "INSERT OR IGNORE INTO relationships "
            "(id, source_type, source_id, target_type, target_id, relationship_type) VALUES (?, ?, ?, ?, ?, ?)"
        )
        values = [
            f"rel-{source_id}-{target_id}-{relationship_type}",
            source_type,
            source_id,
            target_type,
            target_id,
            relationship_type,
        ]
        if cursor is None:
            self.db.execute_query(sql, values)
        else:
            cursor.execute(sql, values)

    def _apply_edit(
        self,
        table: str,
        entity_type: str,
        entity_id: str,
        changes: dict[str, Any],
        *,
        editable: Iterable[str],
        json_fields: Iterable[str] = (),
        actor: str = "MCP User",
        reason: str | None = None,
        if_revision: int | None = None,
        check: Callable[[dict[str, Any]], None] | None = None,
        relink: Callable[[sqlite3.Cursor, dict[str, Any]], dict[str, tuple[Any, Any]]] | None = None,
    ) -> EditResult:
        """Apply content edits to one record atomically; every update tool goes through here.

        In one transaction: checks if_revision, writes only fields whose value actually changes, bumps
        revision once, and logs one lifecycle_events row per changed field with before and after values,
        actor and reason. JSON fields are compared by value, not by their stored text.

        check receives the record as stored and raises EditRefused when a lifecycle rule forbids the edit.
        relink changes the record's links through the transaction's cursor and returns {field: (before, after)}
        for each link field it changed; those count as changed fields and are logged the same way.

        Raises ValueError for a field that isn't editable, LookupError when the record doesn't exist,
        RevisionConflict when if_revision is stale and EditRefused from check or relink. Nothing is written in
        any of those cases, nor when a constraint rejects one of the new values.
        """
        editable, json_fields = set(editable), set(json_fields)
        not_editable = set(changes) - editable
        if not_editable:
            raise ValueError(f"Not editable: {', '.join(sorted(not_editable))}")

        with self.db.transaction(row_factory=True) as cur:
            row = cur.execute(f"SELECT * FROM {table} WHERE id = ?", [entity_id]).fetchone()
            if row is None:
                raise LookupError(f"{entity_type.capitalize()} {entity_id} not found")
            before = dict(row)
            if if_revision is not None and before["revision"] != if_revision:
                raise RevisionConflict(entity_id, before["revision"], if_revision)
            if check is not None:
                check(before)

            updates: dict[str, Any] = {}
            for name, value in changes.items():
                stored = json.dumps(value) if name in json_fields else value
                if name in json_fields and before[name] is not None:
                    try:
                        unchanged = json.loads(before[name]) == value
                    except (TypeError, ValueError):
                        unchanged = False
                else:
                    unchanged = before[name] == stored
                if not unchanged:
                    updates[name] = stored

            links = relink(cur, before) if relink is not None else {}

            if not updates and not links:
                return EditResult([], before["revision"], before)

            assignments = "".join(f"{name} = ?, " for name in updates)
            cur.execute(
                f"UPDATE {table} SET {assignments}revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND revision = ?",
                [*updates.values(), entity_id, before["revision"]],
            )
            if cur.rowcount != 1:  # another writer bumped the revision since we read the row
                current = cur.execute(f"SELECT revision FROM {table} WHERE id = ?", [entity_id]).fetchone()[0]
                raise RevisionConflict(entity_id, current, before["revision"])
            edits = [(name, before[name], stored) for name, stored in updates.items()]
            edits += [(name, old, new) for name, (old, new) in links.items()]
            for name, old, new in edits:
                cur.execute(
                    "INSERT INTO lifecycle_events "
                    "(entity_type, entity_id, event_type, field, from_value, to_value, actor, reason) "
                    "VALUES (?, ?, 'field_edit', ?, ?, ?, ?, ?)",
                    [entity_type, entity_id, name, old, new, actor, reason],
                )
            return EditResult([name for name, _, _ in edits], before["revision"] + 1, before)

    @staticmethod
    def _describe_edit(result: EditResult) -> str:
        """Action line for an update tool's response"""
        if not result.changed:
            return f"No changes: every value already matched (revision {result.revision})"
        return f"✏️ Changed {', '.join(result.changed)} | revision {result.revision}"

    def _delete_entity(
        self,
        table: str,
        entity_type: str,
        entity_id: str,
        *,
        deletable_status: str,
        blockers: list[tuple[str, str]],
        actor: str = "MCP User",
    ) -> int:
        """Delete an early-stage record together with the links it owns; returns how many links went with it.

        blockers are (label, SQL) pairs; each query receives entity_id for every `?` and returns the IDs of
        records that depend on this one. Raises LookupError when the record doesn't exist and DeleteRefused
        when it is past deletable_status or anything depends on it; nothing is written in either case.
        The deletion is logged so get_entity_history still explains what happened.
        """
        noun = entity_type.capitalize()
        with self.db.transaction(row_factory=True) as cur:
            row = cur.execute(f"SELECT status FROM {table} WHERE id = ?", [entity_id]).fetchone()
            if row is None:
                raise LookupError(f"{noun} {entity_id} not found")
            if row["status"] != deletable_status:
                raise DeleteRefused(
                    f"{noun} {entity_id} is {row['status']}; only {deletable_status} records can be deleted. "
                    "Change its status instead (for example to Deprecated or Abandoned)."
                )
            dependents = []
            for label, sql in blockers:
                ids = [found[0] for found in cur.execute(sql, [entity_id] * sql.count("?")).fetchall()]
                if ids:
                    dependents.append(f"{label}: {', '.join(ids)}")
            if dependents:
                raise DeleteRefused(
                    f"{noun} {entity_id} cannot be deleted because other records depend on it "
                    f"({'; '.join(dependents)})."
                )
            removed = cur.execute(
                "DELETE FROM relationships WHERE source_id = ? OR target_id = ?", [entity_id, entity_id]
            ).rowcount
            cur.execute(f"DELETE FROM {table} WHERE id = ?", [entity_id])
            cur.execute(
                "INSERT INTO lifecycle_events (entity_type, entity_id, event_type, actor) VALUES (?, ?, 'deleted', ?)",
                [entity_type, entity_id, actor],
            )
        return removed

    def _log_operation(self, entity_type: str, entity_id: str, event_type: str, actor: str = "MCP User"):
        """Log lifecycle events"""
        try:
            self.db.insert_record(
                "lifecycle_events",
                {"entity_type": entity_type, "entity_id": entity_id, "event_type": event_type, "actor": actor},
            )
        except Exception as e:
            self.logger.warning(f"Failed to log event: {str(e)}")

    def _add_review_comment(self, entity_type: str, entity_id: str, comment: str, reviewer: str = "MCP User"):
        """Add review comment to an entity"""
        try:
            self.db.insert_record(
                "reviews",
                {"entity_type": entity_type, "entity_id": entity_id, "reviewer": reviewer, "comment": comment},
            )
        except Exception as e:
            self.logger.warning(f"Failed to add review comment: {str(e)}")

    @abstractmethod
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return list of tool definitions this handler provides"""
        pass

    @abstractmethod
    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle a tool call for this handler's domain"""
        pass
