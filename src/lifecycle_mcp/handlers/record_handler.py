#!/usr/bin/env python3
"""
Record Handler for MCP Lifecycle Management Server
Tools that take any record's ID: details, delete and comments (ADR-0002)
"""

from typing import Any

from mcp.types import TextContent

from .architecture_handler import ArchitectureHandler
from .base_handler import ENTITY_TABLES, BaseHandler
from .requirement_handler import RequirementHandler
from .task_handler import TaskHandler

ID_EXAMPLES = "REQ-0001-FUNC-00, TASK-0001-00-00 or ADR-0001"
RECORD_TOOLS = ("get_details", "delete_record", "add_comment")


class RecordHandler(BaseHandler):
    """ID-only operations shared by requirements, tasks and architecture decisions; the ID prefix gives the type"""

    def __init__(
        self,
        db_manager,
        requirement_handler: RequirementHandler,
        task_handler: TaskHandler,
        architecture_handler: ArchitectureHandler,
    ):
        super().__init__(db_manager)
        self.requirements = requirement_handler
        self.tasks = task_handler
        self.architecture = architecture_handler

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return record tool definitions"""
        return [
            {
                "name": "get_details",
                "description": "Full details of a requirement, task or architecture decision, with links and comments",
                "inputSchema": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                },
            },
            {
                "name": "delete_record",
                "description": (
                    "Delete a record created by mistake: a Draft requirement, Not Started task or Proposed "
                    "architecture decision that nothing depends on. Refusals name what blocks it; otherwise change "
                    "its status instead."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                },
            },
            {
                "name": "add_comment",
                "description": "Comment on a requirement, task or architecture decision; shown in details and history",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "comment": {"type": "string"},
                        "author": {"type": "string"},
                    },
                    "required": ["entity_id", "comment"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Route a record tool call to the handler for the record's type"""
        if tool_name not in RECORD_TOOLS:
            return self._create_error_response(f"Unknown tool: {tool_name}")
        try:
            error = self._validate_required_params(arguments, ["entity_id"])
            if error:
                return self._create_error_response(error)
            entity_id = arguments["entity_id"]
            entity_type = self._get_entity_type(entity_id)
            if entity_type is None:
                return self._create_error_response(f"Invalid entity ID: {entity_id}. Expected an ID like {ID_EXAMPLES}")
            if tool_name == "get_details":
                return self._get_details(entity_type, entity_id)
            if tool_name == "delete_record":
                return self._delete_record(entity_type, entity_id)
            return self._add_comment(entity_type, entity_id, arguments)
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    def _get_details(self, entity_type: str, entity_id: str) -> list[TextContent]:
        if entity_type == "requirement":
            return self.requirements._get_requirement_details(requirement_id=entity_id)
        if entity_type == "task":
            return self.tasks._get_task_details(task_id=entity_id)
        return self.architecture._get_architecture_details(architecture_id=entity_id)

    def _delete_record(self, entity_type: str, entity_id: str) -> list[TextContent]:
        if entity_type == "requirement":
            return self.requirements._delete_requirement(requirement_id=entity_id)
        if entity_type == "task":
            return self.tasks._delete_task(task_id=entity_id)
        return self.architecture._delete_architecture(architecture_id=entity_id)

    def _add_comment(self, entity_type: str, entity_id: str, arguments: dict[str, Any]) -> list[TextContent]:
        error = self._validate_required_params(arguments, ["comment"])
        if error:
            return self._create_error_response(error)
        if not self.db.check_exists(ENTITY_TABLES[entity_type], "id = ?", [entity_id]):
            return self._create_error_response(f"No {entity_type} {entity_id} found")
        author = arguments.get("author") or "MCP User"
        self.db.insert_record(
            "reviews",
            {"entity_type": entity_type, "entity_id": entity_id, "reviewer": author, "comment": arguments["comment"]},
        )
        return self._create_above_fold_response("SUCCESS", f"Comment added to {entity_id}", f"📝 by {author}")
