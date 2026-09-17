#!/usr/bin/env python3
"""
Relationship Handler for MCP Lifecycle Management Server
Handles all entity relationship operations (CRUD)
"""

from typing import Any

from mcp.types import TextContent

from .base_handler import ENTITY_TABLES, BaseHandler


class RelationshipHandler(BaseHandler):
    """Handler for entity relationship operations"""

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return relationship tool definitions"""
        return [
            {
                "name": "create_relationship",
                "description": (
                    "Link two records; reads source_id relationship_type target_id (ADR-0005 supersedes ADR-0004)"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "target_id": {"type": "string"},
                        "relationship_type": {
                            "type": "string",
                            "enum": [
                                "implements",  # task implements requirement or architecture decision
                                "addresses",  # architecture addresses requirement
                                "depends",  # entity depends on another
                                "blocks",  # entity blocks another
                                "informs",  # entity informs another
                                "requires",  # entity requires another
                                "parent",  # parent-child relationship
                                "refines",  # refines another entity
                                "conflicts",  # conflicts with another entity
                                "relates",  # generic relationship
                                "supersedes",  # newer architecture decision replaces an older one
                            ],
                        },
                    },
                    "required": ["source_id", "target_id", "relationship_type"],
                },
            },
            {
                "name": "delete_relationship",
                "description": "Delete relationship between entities",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "target_id": {"type": "string"},
                        "relationship_type": {"type": "string"},
                    },
                    "required": ["source_id", "target_id"],
                },
            },
            {
                "name": "query_relationships",
                "description": "One record's links by direction and type, or without entity_id every link as JSON",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "relationship_type": {"type": "string"},
                        "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"]},
                        "entity_types": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["requirement", "task", "architecture"]},
                        },
                    },
                },
            },
            {
                "name": "get_entity_history",
                "description": "A record's history: creation, edits (before, after, reason), status changes, comments",
                "inputSchema": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle relationship tool calls"""
        try:
            if tool_name == "create_relationship":
                return await self._create_relationship(arguments)
            elif tool_name == "delete_relationship":
                return await self._delete_relationship(arguments)
            elif tool_name == "query_relationships":
                return await self._query_relationships(arguments)
            elif tool_name == "get_entity_history":
                return self._get_entity_history(arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")

        except Exception as e:
            return self._create_error_response(f"Error in {tool_name}", e)

    def _get_entity_history(self, args: dict[str, Any]) -> list[TextContent]:
        """Creation, field edits, status changes, comments and deletion for one record, oldest first"""
        error = self._validate_required_params(args, ["entity_id"])
        if error:
            return self._create_error_response(error)
        entity_id = args["entity_id"]
        entity_type = self._get_entity_type(entity_id)
        if not entity_type:
            return self._create_error_response(f"Invalid entity ID: {entity_id}")

        events = self.db.execute_query(
            "SELECT occurred_at, id, event_type, field, from_value, to_value, actor, reason FROM lifecycle_events "
            "WHERE entity_type = ? AND entity_id = ?",
            [entity_type, entity_id],
            fetch_all=True,
            row_factory=True,
        )
        comments = self.db.execute_query(
            "SELECT created_at, id, reviewer, comment FROM reviews WHERE entity_type = ? AND entity_id = ?",
            [entity_type, entity_id],
            fetch_all=True,
            row_factory=True,
        )
        exists = self.db.check_exists(ENTITY_TABLES[entity_type], "id = ?", [entity_id])
        if not events and not comments and not exists:
            return self._create_error_response(f"No record or history found for {entity_id}")

        # Timestamps have one-second resolution; within a second, events are listed before comments.
        entries = [(row["occurred_at"], 0, row["id"], self._describe_event(row)) for row in events]
        entries += [
            (row["created_at"], 1, row["id"], f"comment by {row['reviewer']}: {self._clip(row['comment'])}")
            for row in comments
        ]
        entries.sort()

        details = f"# History for {entity_id}\n\n" + "\n".join(f"- {when} {text}" for when, _, _, text in entries)
        state = "" if exists else " | record deleted"
        return self._create_above_fold_response(
            "INFO", f"History for {entity_id}", f"🕘 {len(entries)} entries{state}", details
        )

    @staticmethod
    def _clip(value: Any, limit: int = 160) -> str:
        if value is None or value == "":
            return "(empty)"
        text = str(value)
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _describe_event(self, row) -> str:
        by = f" by {row['actor']}" if row["actor"] else ""
        if row["event_type"] == "field_edit":
            text = f"edited {row['field']}{by}: {self._clip(row['from_value'])} → {self._clip(row['to_value'])}"
            return text + (f" (reason: {self._clip(row['reason'])})" if row["reason"] else "")
        if row["event_type"] == "status_change":
            return f"status {row['from_value']} → {row['to_value']}{by}"
        if row["event_type"] == "amendment":
            # Its own kind of entry: not an edit of the decision, and not a comment about it (roadmap R20)
            text = f"amended {row['field']}{by}: {self._clip(row['to_value'])}"
            return text + (f" (reason: {self._clip(row['reason'])})" if row["reason"] else "")
        return f"{row['event_type']}{by}"

    async def _create_relationship(self, args: dict[str, Any]) -> list[TextContent]:
        """Create a relationship between two entities"""
        error = self._validate_required_params(args, ["source_id", "target_id", "relationship_type"])
        if error:
            return self._create_error_response(error)

        source_id = args["source_id"]
        target_id = args["target_id"]
        rel_type = args["relationship_type"]

        # Determine entity types from IDs
        source_type = self._get_entity_type(source_id)
        target_type = self._get_entity_type(target_id)

        if not source_type or not target_type:
            return self._create_error_response(f"Invalid entity IDs: {source_id}, {target_id}")

        # Validate relationship makes sense
        if not self._validate_relationship(source_type, target_type, rel_type):
            return self._create_error_response(f"Invalid relationship: {source_type} -> {target_type} ({rel_type})")

        source_id, target_id, source_type, target_type = self._normalize_direction(
            source_id, target_id, source_type, target_type
        )

        # Check if relationship already exists
        if self._relationship_exists(source_id, target_id, rel_type):
            return self._create_error_response(f"Relationship already exists: {source_id} -> {target_id} ({rel_type})")

        if rel_type == "supersedes":
            return self._supersede(source_id, target_id)

        # Create the relationship in appropriate table
        success = self._insert_relationship(source_id, target_id, source_type, target_type, rel_type)

        if success:
            # Log the operation
            self._log_operation("relationship", f"{source_id}-{target_id}", "created")

            return self._create_above_fold_response(
                "SUCCESS",
                f"Relationship created: {source_id} -> {target_id}",
                f"Type: {rel_type}",
            )
        else:
            return self._create_error_response("Failed to create relationship")

    async def _delete_relationship(self, args: dict[str, Any]) -> list[TextContent]:
        """Delete a relationship between two entities"""
        error = self._validate_required_params(args, ["source_id", "target_id"])
        if error:
            return self._create_error_response(error)

        source_id = args["source_id"]
        target_id = args["target_id"]
        rel_type = args.get("relationship_type")

        # Determine entity types
        source_type = self._get_entity_type(source_id)
        target_type = self._get_entity_type(target_id)

        if not source_type or not target_type:
            return self._create_error_response(f"Invalid entity IDs: {source_id}, {target_id}")

        source_id, target_id, source_type, target_type = self._normalize_direction(
            source_id, target_id, source_type, target_type
        )

        # Delete the relationship
        deleted_count = self._delete_relationship_record(source_id, target_id, source_type, target_type, rel_type)

        if deleted_count > 0:
            # Log the operation
            self._log_operation("relationship", f"{source_id}-{target_id}", "deleted")

            return self._create_above_fold_response(
                "SUCCESS",
                f"Deleted {deleted_count} relationship(s): {source_id} -> {target_id}",
            )
        else:
            return self._create_error_response(f"No relationship found between {source_id} and {target_id}")

    async def _query_relationships(self, args: dict[str, Any]) -> list[TextContent]:
        """One record's links (optionally by direction), or every link as JSON for building a graph"""
        entity_id = args.get("entity_id")
        rel_type = args.get("relationship_type")
        direction = args.get("direction")
        entity_types = args.get("entity_types")

        if entity_id and not self._get_entity_type(entity_id):
            return self._create_error_response(f"Invalid entity ID: {entity_id}")
        if direction and not entity_id:
            return self._create_error_response(
                "direction needs entity_id: it selects that record's incoming or outgoing links"
            )

        relationships = self._fetch_all_relationships()
        if rel_type:
            relationships = [r for r in relationships if r["type"] == rel_type]
        if entity_types:
            relationships = [
                r
                for r in relationships
                if self._get_entity_type(r["source_id"]) in entity_types
                and self._get_entity_type(r["target_id"]) in entity_types
            ]

        if not entity_id:
            details = self._format_all_relationships_json(relationships)
            return self._create_above_fold_response(
                "SUCCESS", f"Found {len(relationships)} relationship(s)", "", details
            )

        outgoing = direction in (None, "both", "outgoing")
        incoming = direction in (None, "both", "incoming")
        relationships = [
            r
            for r in relationships
            if (outgoing and r["source_id"] == entity_id) or (incoming and r["target_id"] == entity_id)
        ]
        key_info = f"Entity {entity_id} has {len(relationships)} relationship(s)"
        details = self._format_entity_relationships_details(entity_id, relationships)
        return self._create_above_fold_response("SUCCESS", key_info, "", details)

    @staticmethod
    def _normalize_direction(source_id: str, target_id: str, source_type: str, target_type: str):
        """Requirement links are stored requirement -> task/architecture and design links task -> architecture;
        accept either direction from callers."""
        if target_type == "requirement" and source_type in ("task", "architecture"):
            return target_id, source_id, target_type, source_type
        if source_type == "architecture" and target_type == "task":
            return target_id, source_id, target_type, source_type
        return source_id, target_id, source_type, target_type

    def _supersede(self, newer_id: str, older_id: str) -> list[TextContent]:
        """Link newer_id supersedes older_id and move older_id to Superseded, together (ADR-0003).

        The link's trigger sets older_id's superseded_by. Refused for a decision superseding itself, an older decision
        that is already superseded, and a newer decision that is itself Superseded, which also rules out cycles.
        """
        if newer_id == older_id:
            return self._create_error_response(f"{newer_id} can't supersede itself")
        rows = self.db.execute_query(
            "SELECT id, status, superseded_by FROM architecture WHERE id IN (?, ?)",
            [newer_id, older_id],
            fetch_all=True,
            row_factory=True,
        )
        decisions = {row["id"]: row for row in rows or []}
        for decision_id in (newer_id, older_id):
            if decision_id not in decisions:
                return self._create_error_response(f"Architecture decision {decision_id} not found")
        if decisions[older_id]["superseded_by"]:
            return self._create_error_response(
                f"{older_id} is already superseded by {decisions[older_id]['superseded_by']}"
            )
        if decisions[newer_id]["status"] == "Superseded":
            return self._create_error_response(
                f"{newer_id} is itself Superseded; link from the decision that replaced it"
            )

        with self.db.transaction() as cur:
            self._link("architecture", newer_id, "architecture", older_id, "supersedes", cursor=cur)
            # CURRENT_TIMESTAMP has to be SQL, not a bound value (F-42).
            cur.execute(
                "UPDATE architecture SET status = 'Superseded', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status != 'Superseded'",
                [older_id],
            )
        self._log_operation("relationship", f"{newer_id}-{older_id}", "created")
        return self._create_above_fold_response(
            "SUCCESS",
            f"Relationship created: {newer_id} -> {older_id}",
            f"Type: supersedes | {older_id} is now Superseded",
        )

    def _validate_relationship(self, source_type: str, target_type: str, rel_type: str) -> bool:
        """Validate that relationship type is valid for entity types"""
        valid_combinations = {
            ("requirement", "task", "implements"): True,
            ("task", "requirement", "implements"): True,  # Reverse is also valid
            ("requirement", "architecture", "addresses"): True,
            ("architecture", "requirement", "addresses"): True,
            ("task", "architecture", "implements"): True,
            ("architecture", "task", "implements"): True,  # Reverse is also valid
            ("architecture", "architecture", "supersedes"): True,  # newer -> older
            ("task", "task", "depends"): True,
            ("task", "task", "blocks"): True,
            ("task", "task", "informs"): True,
            ("task", "task", "requires"): True,
            ("requirement", "requirement", "depends"): True,
            ("requirement", "requirement", "parent"): True,
            ("requirement", "requirement", "refines"): True,
            ("requirement", "requirement", "conflicts"): True,
            ("requirement", "requirement", "relates"): True,
        }

        return valid_combinations.get((source_type, target_type, rel_type), False)

    def _relationship_exists(self, source_id: str, target_id: str, rel_type: str) -> bool:
        """Check if relationship already exists in unified relationships table"""
        source_type = self._get_entity_type(source_id)
        target_type = self._get_entity_type(target_id)

        if not source_type or not target_type:
            return False

        # Check unified relationships table
        results = self.db.get_records(
            "relationships",
            "1",
            "source_type = ? AND source_id = ? AND target_type = ? AND target_id = ? AND relationship_type = ?",
            [source_type, source_id, target_type, target_id, rel_type],
        )
        return len(results) > 0

    def _insert_relationship(
        self, source_id: str, target_id: str, source_type: str, target_type: str, rel_type: str
    ) -> bool:
        """Insert relationship into unified relationships table"""
        try:
            # Generate unique relationship ID
            relationship_id = f"rel-{source_id}-{target_id}-{rel_type}"

            # Insert into unified relationships table
            self.db.insert_record(
                "relationships",
                {
                    "id": relationship_id,
                    "source_type": source_type,
                    "source_id": source_id,
                    "target_type": target_type,
                    "target_id": target_id,
                    "relationship_type": rel_type,
                },
            )

            return True
        except Exception as e:
            self.logger.error(f"Failed to insert relationship: {str(e)}")
            return False

    def _delete_relationship_record(
        self, source_id: str, target_id: str, source_type: str, target_type: str, rel_type: str | None = None
    ) -> int:
        """Delete relationship record from unified relationships table and return count of deleted records"""
        try:
            if not source_type or not target_type:
                return 0

            # Build WHERE clause for unified relationships table
            if rel_type:
                where_clause = (
                    "source_type = ? AND source_id = ? AND target_type = ? AND target_id = ? AND relationship_type = ?"
                )
                params = [source_type, source_id, target_type, target_id, rel_type]
            else:
                where_clause = "source_type = ? AND source_id = ? AND target_type = ? AND target_id = ?"
                params = [source_type, source_id, target_type, target_id]

            # Get count before deletion for return value
            existing = self.db.get_records("relationships", "COUNT(*) as count", where_clause, params)
            count = existing[0]["count"] if existing else 0

            if count > 0:
                self.db.delete_record("relationships", where_clause, params)
                return count

            return 0

        except Exception as e:
            self.logger.error(f"Failed to delete relationship: {str(e)}")
            return 0

    def _fetch_all_relationships(self) -> list[dict[str, Any]]:
        """Fetch all relationships from unified relationships table"""
        relationships = []

        # Get all relationships from unified table
        relationship_rows = self.db.get_records("relationships", "*")

        for row in relationship_rows:
            source_id = row["source_id"]
            target_id = row["target_id"]
            source_type = row["source_type"]
            target_type = row["target_type"]

            # Get source entity title
            source_title = source_id  # Default fallback
            if source_type == "requirement":
                source_rows = self.db.get_records("requirements", "title", "id = ?", [source_id])
                if source_rows:
                    source_title = source_rows[0]["title"]
            elif source_type == "task":
                source_rows = self.db.get_records("tasks", "title", "id = ?", [source_id])
                if source_rows:
                    source_title = source_rows[0]["title"]
            elif source_type == "architecture":
                source_rows = self.db.get_records("architecture", "title", "id = ?", [source_id])
                if source_rows:
                    source_title = source_rows[0]["title"]

            # Get target entity title
            target_title = target_id  # Default fallback
            if target_type == "requirement":
                target_rows = self.db.get_records("requirements", "title", "id = ?", [target_id])
                if target_rows:
                    target_title = target_rows[0]["title"]
            elif target_type == "task":
                target_rows = self.db.get_records("tasks", "title", "id = ?", [target_id])
                if target_rows:
                    target_title = target_rows[0]["title"]
            elif target_type == "architecture":
                target_rows = self.db.get_records("architecture", "title", "id = ?", [target_id])
                if target_rows:
                    target_title = target_rows[0]["title"]

            relationships.append(
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "type": row["relationship_type"],
                    "source_title": source_title,
                    "target_title": target_title,
                }
            )

        return relationships

    def _format_entity_relationships_details(self, entity_id: str, relationships: list[dict[str, Any]]) -> str:
        """Format entity relationships for detailed display"""
        if not relationships:
            return f"Entity {entity_id} has no relationships."

        lines = [f"# Relationships for {entity_id}\n"]

        # Group by relationship type
        by_type = {}
        for rel in relationships:
            rel_type = rel["type"]
            if rel_type not in by_type:
                by_type[rel_type] = []
            by_type[rel_type].append(rel)

        for rel_type, rels in by_type.items():
            lines.append(f"## {rel_type.title()} ({len(rels)})")
            for rel in rels:
                if rel["source_id"] == entity_id:
                    # Outgoing relationship
                    target_title = rel.get("target_title", rel["target_id"])
                    lines.append(f"- → **{target_title}** ({rel['target_id']})")
                else:
                    # Incoming relationship
                    source_title = rel.get("source_title", rel["source_id"])
                    lines.append(f"- ← **{source_title}** ({rel['source_id']})")
            lines.append("")

        return "\n".join(lines)

    def _format_all_relationships_json(self, relationships: list[dict[str, Any]]) -> str:
        """Format all relationships as JSON for graph visualization"""
        import json

        # Simplify relationships for JSON output
        simplified = []
        for rel in relationships:
            simplified.append(
                {
                    "source": rel["source_id"],
                    "target": rel["target_id"],
                    "type": rel["type"],
                    "source_title": rel.get("source_title", ""),
                    "target_title": rel.get("target_title", ""),
                }
            )

        return f"```json\n{json.dumps(simplified, indent=2)}\n```"
