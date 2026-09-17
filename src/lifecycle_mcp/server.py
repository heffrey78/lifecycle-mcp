#!/usr/bin/env python3
"""
MCP Server for Software Lifecycle Management - Refactored Modular Architecture
Provides structured access to requirements, tasks, and architecture artifacts
"""

import asyncio
import difflib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import jsonschema
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import GetPromptResult, Prompt, TextContent, Tool

from .database_manager import DatabaseManager
from .handlers import (
    ArchitectureHandler,
    ExportHandler,
    RecordHandler,
    RelationshipHandler,
    RequirementHandler,
    StatusHandler,
    TaskHandler,
)
from .handlers.base_handler import ErrorResult, StructuredResult
from .prompts import prompt_definitions, render_prompt
from .short_ids import UnknownAlias, resolve_arguments

logger = logging.getLogger(__name__)

# When set, every tool call is appended to this file as one JSON line (roadmap R15 usage evidence).
CALL_LOG_ENV = "LIFECYCLE_CALL_LOG"


class ToolCallError(Exception):
    """Raised from call_tool so the MCP layer returns the result with isError=true.

    ``kind`` says what refused the call, so the call log can tell a schema refusal from a handler error
    (roadmap R18), and ``rejected`` carries the rule and parameter a schema refusal names.
    """

    def __init__(self, message: str, *, kind: str = "handler", rejected: dict[str, str] | None = None):
        super().__init__(message)
        self.kind = kind
        self.rejected = rejected


# How close a parameter name has to be to count as the one that was meant. requirement_id and requirement_ids
# differ by one character; a parameter that merely happens to accept the value (acceptance_criteria also takes
# an array) is not a suggestion worth making.
NEIGHBOUR_RATIO = 0.8


def _type_name(subschema: dict[str, Any]) -> str:
    """How a schema's declared type reads in a sentence: "a string", "an array"."""
    declared = subschema.get("type")
    if isinstance(declared, str):
        return f"an {declared}" if declared[0] in "aeiou" else f"a {declared}"
    return "another type"


def _accepting_neighbour(schema: dict[str, Any], error: jsonschema.ValidationError) -> str | None:
    """A parameter beside the refused one, close in name, whose own schema accepts the refused value.

    Drawn from the tool's schema rather than a list of known pairs, so a new singular/plural pair is covered
    the day it is declared (roadmap R19).
    """
    if error.validator != "type" or len(error.absolute_path) != 1:
        return None
    parameter = error.absolute_path[0]
    properties = schema.get("properties", {})
    if not isinstance(parameter, str) or parameter not in properties:
        return None

    matches = []
    for name, subschema in properties.items():
        if name == parameter:
            continue
        ratio = difflib.SequenceMatcher(None, parameter, name).ratio()
        if ratio >= NEIGHBOUR_RATIO and jsonschema.validators.validator_for(subschema)(subschema).is_valid(
            error.instance
        ):
            matches.append((ratio, name))
    return max(matches)[1] if matches else None


def _rejected_field(error: jsonschema.ValidationError) -> dict[str, str]:
    """What the call log records about a schema refusal: the rule and the parameter, never the value.

    jsonschema quotes the offending value in its message ("['REQ-1'] is not of type 'string'", and enum
    errors do the same), and the log has never held argument values, so the message cannot go in it. The
    parameter names the log already records under arg_names say the rest (roadmap R18).
    """
    rejected = {"rule": str(error.validator)}
    if len(error.absolute_path) == 1 and isinstance(error.absolute_path[0], str):
        rejected["param"] = error.absolute_path[0]
    return rejected


class LifecycleMCPServer:
    """Refactored MCP Server using modular handler architecture"""

    def __init__(self):
        """Initialize server with database manager and handlers"""
        # Initialize database manager
        self.db_manager = DatabaseManager()

        # Initialize handlers
        self.requirement_handler = RequirementHandler(self.db_manager)
        self.task_handler = TaskHandler(self.db_manager)
        self.architecture_handler = ArchitectureHandler(self.db_manager)
        self.relationship_handler = RelationshipHandler(self.db_manager)
        self.record_handler = RecordHandler(
            self.db_manager, self.requirement_handler, self.task_handler, self.architecture_handler
        )
        self.export_handler = ExportHandler(self.db_manager)
        self.status_handler = StatusHandler(self.db_manager)

        # Create handler registry for tool routing
        self.handlers = {
            # Requirement tools
            "create_requirement": self.requirement_handler,
            "update_requirement_status": self.requirement_handler,
            "query_requirements": self.requirement_handler,
            "trace_requirement": self.requirement_handler,
            "update_requirement": self.requirement_handler,
            # Task tools
            "create_task": self.task_handler,
            "update_task_status": self.task_handler,
            "query_tasks": self.task_handler,
            "sync_github_tasks": self.task_handler,  # listed and routed only when LIFECYCLE_GITHUB=on
            "update_task": self.task_handler,
            # Relationship tools
            "create_relationship": self.relationship_handler,
            "delete_relationship": self.relationship_handler,
            "query_relationships": self.relationship_handler,
            "get_entity_history": self.relationship_handler,
            # Record tools: any requirement, task or architecture decision ID
            "get_details": self.record_handler,
            "delete_record": self.record_handler,
            "add_comment": self.record_handler,
            # Architecture tools
            "create_architecture_decision": self.architecture_handler,
            "update_architecture_status": self.architecture_handler,
            "query_architecture_decisions": self.architecture_handler,
            "update_architecture": self.architecture_handler,
            # Export tools
            "export_project_documentation": self.export_handler,
            "create_architectural_diagrams": self.export_handler,
            # Status tools
            "get_project_status": self.status_handler,
        }

        # Create MCP server instance
        self.server = Server("lifecycle-management")
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP server handlers"""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools from all handlers"""
            tools = self._tool_definitions()
            logger.info(f"Registered {len(tools)} MCP tools")
            return tools

        @self.server.list_prompts()
        async def list_prompts() -> list[Prompt]:
            """Prompts are text the client's model fills in; they cost nothing against the tool budget (R11)."""
            return prompt_definitions()

        @self.server.get_prompt()
        async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
            """One prompt's text. No session is kept: the client's model fills it in and calls the tool."""
            return render_prompt(name, arguments)

        # validate_input=False: the MCP layer would otherwise check the schema and return its own message
        # before this function runs, so a refused call could be neither logged nor explained. Validation
        # happens in _route_tool_call instead, against the same schemas (roadmap R18, R19).
        @self.server.call_tool(validate_input=False)
        async def call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[TextContent] | tuple[list[TextContent], dict[str, Any]]:
            """Route tool calls to appropriate handlers

            Failures are raised as ToolCallError, which the MCP layer turns into a result with
            isError=true carrying the same message text.

            Note: This method is async and must await handler calls for proper MCP protocol compliance.
            All handler.handle_tool_call() methods must also be async to prevent connection issues.
            """
            started = time.monotonic()
            try:
                result = await self._route_tool_call(name, arguments)
            except ToolCallError as e:
                self._record_call(
                    name,
                    arguments,
                    started,
                    is_error=True,
                    response_chars=len(str(e)),
                    error_kind=e.kind,
                    rejected=e.rejected,
                )
                raise
            response_chars = sum(len(getattr(block, "text", "")) for block in result)
            self._record_call(name, arguments, started, is_error=False, response_chars=response_chars)
            if isinstance(result, StructuredResult):
                # The MCP layer returns a (content, data) pair as content plus structuredContent.
                return list(result), result.structured
            return result

    def _tool_definitions(self) -> list[Tool]:
        """Every tool this server lists.

        tools/list serves these and _validate_arguments checks calls against them, so a client is never
        refused by a rule it could not read in the listing.
        """
        tools = []
        for handler in [
            self.requirement_handler,
            self.task_handler,
            self.architecture_handler,
            self.relationship_handler,
            self.record_handler,
            self.export_handler,
            self.status_handler,
        ]:
            for tool_def in handler.get_tool_definitions():
                # Reject undeclared fields instead of silently dropping them.
                input_schema = {"additionalProperties": False, **tool_def["inputSchema"]}
                tools.append(Tool(name=tool_def["name"], description=tool_def["description"], inputSchema=input_schema))
        return tools

    def _validate_arguments(self, name: str, arguments: dict[str, Any]) -> None:
        """Refuse a call whose arguments do not match the tool's schema (roadmap R18, R19).

        The MCP layer would do this before call_tool ran and return its own message, leaving the refusal
        invisible to the call log and impossible to improve; validate_input=False hands it here instead. The
        message is the one the MCP layer produced, plus the parameter that would have taken the value when
        the schema has one beside it.
        """
        schemas = {tool.name: tool.inputSchema for tool in self._tool_definitions()}
        schema = schemas.get(name)
        if schema is None:
            # Not listed, so the MCP layer would not have validated it either (sync_github_tasks with
            # LIFECYCLE_GITHUB off is routed but unlisted). The handler gives its own answer.
            return
        try:
            jsonschema.validate(instance=arguments, schema=schema)
        except jsonschema.ValidationError as e:
            neighbour = _accepting_neighbour(schema, e)
            message = e.message
            if neighbour is not None:
                parameter = str(e.absolute_path[0])
                message = (
                    f"{message}. {parameter} takes {_type_name(e.schema)}; {neighbour} takes "
                    f"{_type_name(schema['properties'][neighbour])} and accepts what you passed"
                )
            raise ToolCallError(
                f"Input validation error: {message}", kind="validation", rejected=_rejected_field(e)
            ) from e

    async def _route_tool_call(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Run the tool's handler; failures raise ToolCallError"""
        handler = self.handlers.get(name)
        if not handler:
            logger.error(f"No handler found for tool: {name}")
            raise ToolCallError(f"[ERROR] Unknown tool: {name}", kind="unknown_tool")

        self._validate_arguments(name, arguments)

        logger.debug(f"Routing tool '{name}' to {handler.__class__.__name__}")
        try:
            # Short IDs are resolved here, so every tool takes them and no handler has to know (roadmap R14).
            arguments = resolve_arguments(self.db_manager, arguments)
        except UnknownAlias as e:
            raise ToolCallError(f"[ERROR] {e}") from e

        try:
            result = await handler.handle_tool_call(name, arguments)
        except Exception as e:
            logger.exception(f"Error handling tool '{name}'")
            raise ToolCallError(f"[ERROR] Error handling {name}: {e}") from e

        if isinstance(result, ErrorResult):
            raise ToolCallError("\n".join(block.text for block in result))
        return result

    def _record_call(
        self,
        name: str,
        arguments: dict[str, Any] | None,
        started: float,
        *,
        is_error: bool,
        response_chars: int,
        error_kind: str | None = None,
        rejected: dict[str, str] | None = None,
    ) -> None:
        """Append the call to the LIFECYCLE_CALL_LOG file when that is set; never fails the call.

        Argument names are recorded, not values. Every call the server receives is logged, including one
        refused by its schema and one naming a tool that does not exist: error_kind tells those apart from a
        handler error, and rejected names the rule and parameter (roadmap R18).
        """
        path = os.environ.get(CALL_LOG_ENV)
        if not path:
            return
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "tool": name,
            "arg_names": sorted(arguments or {}),
            "ms": round((time.monotonic() - started) * 1000),
            "isError": is_error,
            "response_chars": response_chars,
        }
        if is_error:
            record["error_kind"] = error_kind or "handler"
        if rejected:
            record["rejected"] = rejected
        try:
            with open(path, "a", encoding="utf-8") as log:
                log.write(json.dumps(record) + "\n")
        except OSError as e:
            logger.warning(f"Could not write call log {path}: {e}")

    async def run(self):
        """Run the MCP server"""
        logger.info("Starting Lifecycle MCP Server")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, self.server.create_initialization_options())


# Global server instance for backwards compatibility
_server_instance = None


def get_server_instance() -> LifecycleMCPServer:
    """Get or create the global server instance"""
    global _server_instance
    if _server_instance is None:
        _server_instance = LifecycleMCPServer()
    return _server_instance


async def amain():
    """Run the MCP server - backwards compatible entry point"""
    server_instance = get_server_instance()
    await server_instance.run()


def main():
    """Entry point for the lifecycle-mcp command"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
