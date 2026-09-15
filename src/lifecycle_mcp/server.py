#!/usr/bin/env python3
"""
MCP Server for Software Lifecycle Management - Refactored Modular Architecture
Provides structured access to requirements, tasks, and architecture artifacts
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

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
from .handlers.base_handler import ErrorResult

logger = logging.getLogger(__name__)

# When set, every tool call is appended to this file as one JSON line (roadmap R15 usage evidence).
CALL_LOG_ENV = "LIFECYCLE_CALL_LOG"


class ToolCallError(Exception):
    """Raised from call_tool so the MCP layer returns the result with isError=true."""


class LifecycleMCPServer:
    """Refactored MCP Server using modular handler architecture"""

    def __init__(self):
        """Initialize server with database manager and handlers"""
        # Initialize database manager
        self.db_manager = DatabaseManager()

        # MCP client will be set after server creation for LLM analysis features
        self.mcp_client = None

        # Initialize handlers
        self.requirement_handler = RequirementHandler(self.db_manager, self.mcp_client)
        self.task_handler = TaskHandler(self.db_manager)
        self.architecture_handler = ArchitectureHandler(self.db_manager, self.mcp_client)
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
            "query_requirements_json": self.requirement_handler,
            "trace_requirement": self.requirement_handler,
            "update_requirement": self.requirement_handler,
            # Task tools
            "create_task": self.task_handler,
            "update_task_status": self.task_handler,
            "query_tasks": self.task_handler,
            "query_tasks_json": self.task_handler,
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
            "query_architecture_decisions_json": self.architecture_handler,
            "update_architecture": self.architecture_handler,
            # Export tools
            "export_project_documentation": self.export_handler,
            "create_architectural_diagrams": self.export_handler,
            # Status tools
            "get_project_status": self.status_handler,
            "get_project_metrics": self.status_handler,
        }

        # Create MCP server instance
        self.server = Server("lifecycle-management")
        self._register_handlers()

    def set_mcp_client(self, client):
        """Set MCP client for LLM analysis features"""
        self.mcp_client = client
        self.requirement_handler.mcp_client = client
        self.architecture_handler.mcp_client = client

    def _register_handlers(self):
        """Register MCP server handlers"""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools from all handlers"""
            tools = []

            # Collect tool definitions from all handlers
            for handler in [
                self.requirement_handler,
                self.task_handler,
                self.architecture_handler,
                self.relationship_handler,
                self.record_handler,
                self.export_handler,
                self.status_handler,
            ]:
                handler_tools = handler.get_tool_definitions()
                # Convert to Tool objects
                for tool_def in handler_tools:
                    # Reject undeclared fields instead of silently dropping them. The MCP layer validates
                    # calls against this schema, so every tool gets it unless its definition opts out.
                    input_schema = {"additionalProperties": False, **tool_def["inputSchema"]}
                    tools.append(
                        Tool(
                            name=tool_def["name"],
                            description=tool_def["description"],
                            inputSchema=input_schema,
                        )
                    )

            logger.info(f"Registered {len(tools)} MCP tools")
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
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
                self._record_call(name, arguments, started, is_error=True, response_chars=len(str(e)))
                raise
            response_chars = sum(len(getattr(block, "text", "")) for block in result)
            self._record_call(name, arguments, started, is_error=False, response_chars=response_chars)
            return result

    async def _route_tool_call(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Run the tool's handler; failures raise ToolCallError"""
        handler = self.handlers.get(name)
        if not handler:
            logger.error(f"No handler found for tool: {name}")
            raise ToolCallError(f"[ERROR] Unknown tool: {name}")

        logger.debug(f"Routing tool '{name}' to {handler.__class__.__name__}")
        try:
            result = await handler.handle_tool_call(name, arguments)
        except Exception as e:
            logger.exception(f"Error handling tool '{name}'")
            raise ToolCallError(f"[ERROR] Error handling {name}: {e}") from e

        if isinstance(result, ErrorResult):
            raise ToolCallError("\n".join(block.text for block in result))
        return result

    def _record_call(
        self, name: str, arguments: dict[str, Any] | None, started: float, *, is_error: bool, response_chars: int
    ) -> None:
        """Append the call to the LIFECYCLE_CALL_LOG file when that is set; never fails the call.

        Argument names are recorded, not values. Calls the MCP layer rejects before routing (for example an
        undeclared field) never reach here and are not logged.
        """
        path = os.environ.get(CALL_LOG_ENV)
        if not path:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "tool": name,
            "arg_names": sorted(arguments or {}),
            "ms": round((time.monotonic() - started) * 1000),
            "isError": is_error,
            "response_chars": response_chars,
        }
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
