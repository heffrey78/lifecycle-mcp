#!/usr/bin/env python3
"""
Relationship Handler for MCP Lifecycle Management Server
Handles all entity relationship operations (CRUD)
"""

from typing import Any

from mcp.types import TextContent

from .base_handler import BaseHandler


class RelationshipHandler(BaseHandler):
    """Handler for entity relationship operations"""

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return relationship tool definitions"""
        return [
            {
                "name": "create_relationship",
                "description": "Create relationship between entities",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "target_id": {"type": "string"},
                        "relationship_type": {
                            "type": "string",
                            "enum": [
                                "implements",  # task implements requirement
                                "addresses",   # architecture addresses requirement
                                "depends",     # entity depends on another
                                "blocks",      # entity blocks another
                                "informs",     # entity informs another
                                "requires",    # entity requires another
                                "parent",      # parent-child relationship
                                "refines",     # refines another entity
                                "conflicts",   # conflicts with another entity
                                "relates",     # generic relationship
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
                "description": "Query relationships for visualization",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "relationship_type": {"type": "string"},
                        "include_incoming": {"type": "boolean", "default": True},
                        "include_outgoing": {"type": "boolean", "default": True},
                    },
                },
            },
            {
                "name": "get_entity_relationships",
                "description": "Get all relationships for a specific entity",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                    },
                    "required": ["entity_id"],
                },
            },
            {
                "name": "query_all_relationships",
                "description": "Get all relationships for visualization graph building",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_types": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["requirement", "task", "architecture"]},
                            "default": ["requirement", "task", "architecture"],
                        },
                    },
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
            elif tool_name == "get_entity_relationships":
                return await self._get_entity_relationships(arguments)
            elif tool_name == "query_all_relationships":
                return await self._query_all_relationships(arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")

        except Exception as e:
            return self._create_error_response(f"Error in {tool_name}", e)

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
            return self._create_error_response(
                f"Invalid relationship: {source_type} -> {target_type} ({rel_type})"
            )

        # Check if relationship already exists
        if self._relationship_exists(source_id, target_id, rel_type):
            return self._create_error_response(
                f"Relationship already exists: {source_id} -> {target_id} ({rel_type})"
            )

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
            return self._create_error_response(
                f"No relationship found between {source_id} and {target_id}"
            )

    async def _query_relationships(self, args: dict[str, Any]) -> list[TextContent]:
        """Query relationships for a specific entity or type"""
        entity_id = args.get("entity_id")
        rel_type = args.get("relationship_type")

        relationships = self._fetch_all_relationships()

        # Filter by entity_id if specified
        if entity_id:
            relationships = [r for r in relationships if r["source_id"] == entity_id or r["target_id"] == entity_id]

        # Filter by relationship type if specified
        if rel_type:
            relationships = [r for r in relationships if r.get("type") == rel_type]

        if entity_id:
            key_info = f"Found {len(relationships)} relationship(s) for {entity_id}"
        else:
            key_info = f"Found {len(relationships)} relationship(s) of type {rel_type or 'all'}"

        # Format relationships for display
        details = self._format_relationships_details(relationships)

        return self._create_above_fold_response("SUCCESS", key_info, "", details)

    async def _get_entity_relationships(self, args: dict[str, Any]) -> list[TextContent]:
        """Get all relationships for a specific entity"""
        error = self._validate_required_params(args, ["entity_id"])
        if error:
            return self._create_error_response(error)

        entity_id = args["entity_id"]
        all_relationships = self._fetch_all_relationships()

        # Filter to only relationships involving this entity
        relationships = [r for r in all_relationships if r["source_id"] == entity_id or r["target_id"] == entity_id]

        key_info = f"Entity {entity_id} has {len(relationships)} relationship(s)"
        details = self._format_entity_relationships_details(entity_id, relationships)

        return self._create_above_fold_response("SUCCESS", key_info, "", details)

    async def _query_all_relationships(self, args: dict[str, Any]) -> list[TextContent]:
        """Get all relationships for graph visualization"""
        entity_types = args.get("entity_types", ["requirement", "task", "architecture"])

        all_relationships = self._fetch_all_relationships()

        # Filter by entity types if specified
        if entity_types != ["requirement", "task", "architecture"]:
            filtered_relationships = []
            for rel in all_relationships:
                source_type = self._get_entity_type(rel["source_id"])
                target_type = self._get_entity_type(rel["target_id"])
                if source_type in entity_types and target_type in entity_types:
                    filtered_relationships.append(rel)
            all_relationships = filtered_relationships

        key_info = f"Found {len(all_relationships)} total relationship(s)"
        details = self._format_all_relationships_json(all_relationships)

        return self._create_above_fold_response("SUCCESS", key_info, "", details)

    def _get_entity_type(self, entity_id: str) -> str | None:
        """Determine entity type from ID prefix"""
        if entity_id.startswith("REQ-"):
            return "requirement"
        elif entity_id.startswith("TASK-"):
            return "task"
        elif entity_id.startswith("ADR-") or entity_id.startswith("TDD-"):
            return "architecture"
        return None

    def _validate_relationship(self, source_type: str, target_type: str, rel_type: str) -> bool:
        """Validate that relationship type is valid for entity types"""
        valid_combinations = {
            ("requirement", "task", "implements"): True,
            ("task", "requirement", "implements"): True,  # Reverse is also valid
            ("requirement", "architecture", "addresses"): True,
            ("architecture", "requirement", "addresses"): True,
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
        """Check if relationship already exists"""
        source_type = self._get_entity_type(source_id)
        target_type = self._get_entity_type(target_id)

        if source_type == "requirement" and target_type == "task":
            results = self.db.get_records("requirement_tasks", "1", "requirement_id = ? AND task_id = ?", [source_id, target_id])
            return len(results) > 0
        elif source_type == "task" and target_type == "requirement":
            # Consistent parameter order: always put requirement_id first, task_id second
            results = self.db.get_records("requirement_tasks", "1", "requirement_id = ? AND task_id = ?", [target_id, source_id])
            return len(results) > 0
        elif source_type == "requirement" and target_type == "architecture":
            results = self.db.get_records("requirement_architecture", "1", "requirement_id = ? AND architecture_id = ?", [source_id, target_id])
            return len(results) > 0
        elif source_type == "task" and target_type == "task":
            # For dependencies: task_id is the dependent, depends_on_task_id is the dependency
            results = self.db.get_records("task_dependencies", "1", "task_id = ? AND depends_on_task_id = ? AND dependency_type = ?", [source_id, target_id, rel_type])
            return len(results) > 0
        elif source_type == "requirement" and target_type == "requirement":
            # For dependencies: requirement_id is the dependent, depends_on_requirement_id is the dependency
            results = self.db.get_records("requirement_dependencies", "1", "requirement_id = ? AND depends_on_requirement_id = ? AND dependency_type = ?", [source_id, target_id, rel_type])
            return len(results) > 0

        return False

    def _insert_relationship(self, source_id: str, target_id: str, source_type: str, target_type: str, rel_type: str) -> bool:
        """Insert relationship into appropriate table"""
        try:
            if source_type == "requirement" and target_type == "task" and rel_type == "implements":
                self.db.insert_record("requirement_tasks", {
                    "requirement_id": source_id,
                    "task_id": target_id
                })
            elif source_type == "task" and target_type == "requirement" and rel_type == "implements":
                self.db.insert_record("requirement_tasks", {
                    "requirement_id": target_id,
                    "task_id": source_id
                })
            elif source_type == "requirement" and target_type == "architecture" and rel_type == "addresses":
                self.db.insert_record("requirement_architecture", {
                    "requirement_id": source_id,
                    "architecture_id": target_id,
                    "relationship_type": rel_type
                })
            elif source_type == "architecture" and target_type == "requirement" and rel_type == "addresses":
                self.db.insert_record("requirement_architecture", {
                    "requirement_id": target_id,
                    "architecture_id": source_id,
                    "relationship_type": rel_type
                })
            elif source_type == "task" and target_type == "task":
                # Consistent pattern: source is dependent, target is dependency
                self.db.insert_record("task_dependencies", {
                    "task_id": source_id,
                    "depends_on_task_id": target_id,
                    "dependency_type": rel_type
                })
            elif source_type == "requirement" and target_type == "requirement":
                # Consistent pattern: source is dependent, target is dependency
                self.db.insert_record("requirement_dependencies", {
                    "requirement_id": source_id,
                    "depends_on_requirement_id": target_id,
                    "dependency_type": rel_type
                })
            else:
                return False

            return True
        except Exception as e:
            self.logger.error(f"Failed to insert relationship: {str(e)}")
            return False

    def _delete_relationship_record(self, source_id: str, target_id: str, source_type: str, target_type: str, rel_type: str | None = None) -> int:
        """Delete relationship record and return count of deleted records"""
        try:

            if source_type == "requirement" and target_type == "task":
                self.db.delete_record("requirement_tasks", "requirement_id = ? AND task_id = ?", [source_id, target_id])
                return 1  # Simplified return for now
            elif source_type == "task" and target_type == "requirement":
                self.db.delete_record("requirement_tasks", "requirement_id = ? AND task_id = ?", [target_id, source_id])
                return 1
            elif source_type == "requirement" and target_type == "architecture":
                if rel_type:
                    self.db.delete_record("requirement_architecture", "requirement_id = ? AND architecture_id = ? AND relationship_type = ?", [source_id, target_id, rel_type])
                else:
                    self.db.delete_record("requirement_architecture", "requirement_id = ? AND architecture_id = ?", [source_id, target_id])
                return 1
            elif source_type == "task" and target_type == "task":
                if rel_type:
                    # Consistent with _relationship_exists: source is dependent, target is dependency
                    self.db.delete_record("task_dependencies", "task_id = ? AND depends_on_task_id = ? AND dependency_type = ?", [source_id, target_id, rel_type])
                else:
                    self.db.delete_record("task_dependencies", "task_id = ? AND depends_on_task_id = ?", [source_id, target_id])
                return 1
            elif source_type == "requirement" and target_type == "requirement":
                if rel_type:
                    # Consistent with _relationship_exists: source is dependent, target is dependency
                    self.db.delete_record("requirement_dependencies", "requirement_id = ? AND depends_on_requirement_id = ? AND dependency_type = ?", [source_id, target_id, rel_type])
                else:
                    self.db.delete_record("requirement_dependencies", "requirement_id = ? AND depends_on_requirement_id = ?", [source_id, target_id])
                return 1
            else:
                return 0

        except Exception as e:
            self.logger.error(f"Failed to delete relationship: {str(e)}")
            return 0

    def _fetch_all_relationships(self) -> list[dict[str, Any]]:
        """Fetch all relationships from all tables"""
        relationships = []

        # Requirement -> Task relationships
        req_task_rows = self.db.get_records("requirement_tasks", "*")
        for row in req_task_rows:
            # Get requirement and task titles separately
            req_rows = self.db.get_records("requirements", "title", "id = ?", [row["requirement_id"]])
            task_rows = self.db.get_records("tasks", "title", "id = ?", [row["task_id"]])

            req_title = req_rows[0]["title"] if req_rows else row["requirement_id"]
            task_title = task_rows[0]["title"] if task_rows else row["task_id"]

            relationships.append({
                "source_id": row["requirement_id"],
                "target_id": row["task_id"],
                "type": "implements",
                "source_title": req_title,
                "target_title": task_title
            })

        # Requirement -> Architecture relationships
        req_arch_rows = self.db.get_records("requirement_architecture", "*")
        for row in req_arch_rows:
            # Get requirement and architecture titles separately
            req_rows = self.db.get_records("requirements", "title", "id = ?", [row["requirement_id"]])
            arch_rows = self.db.get_records("architecture", "title", "id = ?", [row["architecture_id"]])

            req_title = req_rows[0]["title"] if req_rows else row["requirement_id"]
            arch_title = arch_rows[0]["title"] if arch_rows else row["architecture_id"]

            relationships.append({
                "source_id": row["requirement_id"],
                "target_id": row["architecture_id"],
                "type": row.get("relationship_type", "addresses"),
                "source_title": req_title,
                "target_title": arch_title
            })

        # Task dependencies
        task_dep_rows = self.db.get_records("task_dependencies", "*")
        for row in task_dep_rows:
            # Get task titles separately
            source_rows = self.db.get_records("tasks", "title", "id = ?", [row["depends_on_task_id"]])
            target_rows = self.db.get_records("tasks", "title", "id = ?", [row["task_id"]])

            source_title = source_rows[0]["title"] if source_rows else row["depends_on_task_id"]
            target_title = target_rows[0]["title"] if target_rows else row["task_id"]

            relationships.append({
                "source_id": row["depends_on_task_id"],
                "target_id": row["task_id"],
                "type": row.get("dependency_type", "depends"),
                "source_title": source_title,
                "target_title": target_title
            })

        # Requirement dependencies
        req_dep_rows = self.db.get_records("requirement_dependencies", "*")
        for row in req_dep_rows:
            # Get requirement titles separately
            source_rows = self.db.get_records("requirements", "title", "id = ?", [row["depends_on_requirement_id"]])
            target_rows = self.db.get_records("requirements", "title", "id = ?", [row["requirement_id"]])

            source_title = source_rows[0]["title"] if source_rows else row["depends_on_requirement_id"]
            target_title = target_rows[0]["title"] if target_rows else row["requirement_id"]

            relationships.append({
                "source_id": row["depends_on_requirement_id"],
                "target_id": row["requirement_id"],
                "type": row.get("dependency_type", "depends"),
                "source_title": source_title,
                "target_title": target_title
            })

        return relationships

    def _format_relationships_details(self, relationships: list[dict[str, Any]]) -> str:
        """Format relationships for display"""
        if not relationships:
            return "No relationships found."

        lines = ["# Relationships\n"]
        for rel in relationships:
            source_title = rel.get("source_title", rel["source_id"])
            target_title = rel.get("target_title", rel["target_id"])
            rel_type = rel["type"]

            lines.append(f"- **{source_title}** ({rel['source_id']}) → **{target_title}** ({rel['target_id']}) [{rel_type}]")

        return "\n".join(lines)

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
            simplified.append({
                "source": rel["source_id"],
                "target": rel["target_id"],
                "type": rel["type"],
                "source_title": rel.get("source_title", ""),
                "target_title": rel.get("target_title", "")
            })

        return f"```json\n{json.dumps(simplified, indent=2)}\n```"
