#!/usr/bin/env python3
"""
MCP Server for Software Lifecycle Management - Refactored Modular Architecture
Provides structured access to requirements, tasks, and architecture artifacts
"""

import asyncio
import logging
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .database_manager import DatabaseManager
from .handlers import (
    ArchitectureHandler,
    ExportHandler,
    InterviewHandler,
    RequirementHandler,
    StatusHandler,
    TaskHandler,
)
from .config import config
from .github_utils import GitHubUtils

logger = logging.getLogger(__name__)


class LifecycleMCPServer:
    """Refactored MCP Server using modular handler architecture"""

    def __init__(self):
        """Initialize server with database manager and handlers"""
        # Validate configuration on startup
        self._validate_configuration()
        
        # Initialize database manager
        self.db_manager = DatabaseManager()

        # MCP client will be set after server creation for LLM analysis features
        self.mcp_client = None

        # Initialize handlers
        self.requirement_handler = RequirementHandler(self.db_manager, self.mcp_client)
        self.task_handler = TaskHandler(self.db_manager)
        self.architecture_handler = ArchitectureHandler(self.db_manager, self.mcp_client)
        self.interview_handler = InterviewHandler(self.db_manager, self.requirement_handler)
        self.export_handler = ExportHandler(self.db_manager)
        self.status_handler = StatusHandler(self.db_manager)

        # Create handler registry for tool routing
        self.handlers = {
            # Requirement tools
            "create_requirement": self.requirement_handler,
            "update_requirement_status": self.requirement_handler,
            "query_requirements": self.requirement_handler,
            "get_requirement_details": self.requirement_handler,
            "trace_requirement": self.requirement_handler,
            # Task tools
            "create_task": self.task_handler,
            "update_task_status": self.task_handler,
            "query_tasks": self.task_handler,
            "get_task_details": self.task_handler,
            "sync_task_from_github": self.task_handler,
            "bulk_sync_github_tasks": self.task_handler,
            # Architecture tools
            "create_architecture_decision": self.architecture_handler,
            "update_architecture_status": self.architecture_handler,
            "query_architecture_decisions": self.architecture_handler,
            "get_architecture_details": self.architecture_handler,
            "add_architecture_review": self.architecture_handler,
            # Interview tools
            "start_requirement_interview": self.interview_handler,
            "continue_requirement_interview": self.interview_handler,
            "start_architectural_conversation": self.interview_handler,
            "continue_architectural_conversation": self.interview_handler,
            # Export tools
            "export_project_documentation": self.export_handler,
            "create_architectural_diagrams": self.export_handler,
            # Status tools
            "get_project_status": self.status_handler,
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
        async def list_tools() -> List[Tool]:
            """List available tools from all handlers"""
            tools = []

            # Collect tool definitions from all handlers
            for handler in [
                self.requirement_handler,
                self.task_handler,
                self.architecture_handler,
                self.interview_handler,
                self.export_handler,
                self.status_handler,
            ]:
                handler_tools = handler.get_tool_definitions()
                # Convert to Tool objects
                for tool_def in handler_tools:
                    tools.append(
                        Tool(
                            name=tool_def["name"],
                            description=tool_def["description"],
                            inputSchema=tool_def["inputSchema"],
                        )
                    )

            logger.info(f"Registered {len(tools)} MCP tools")
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Route tool calls to appropriate handlers

            Note: This method is async and must await handler calls for proper MCP protocol compliance.
            All handler.handle_tool_call() methods must also be async to prevent connection issues.
            """
            try:
                # Find the appropriate handler for this tool
                handler = self.handlers.get(name)
                if not handler:
                    logger.error(f"No handler found for tool: {name}")
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]

                # Delegate to the handler
                logger.debug(f"Routing tool '{name}' to {handler.__class__.__name__}")
                return await handler.handle_tool_call(name, arguments)

            except Exception as e:
                logger.error(f"Error handling tool '{name}': {str(e)}")
                return [TextContent(type="text", text=f"Error handling {name}: {str(e)}")]

    def _validate_configuration(self):
        """Validate server configuration on startup"""
        logger.info("Validating server configuration...")
        
        # Validate GitHub configuration if enabled
        if config.is_github_integration_enabled():
            logger.info("GitHub integration is enabled, validating configuration...")
            is_valid, errors = GitHubUtils.validate_github_configuration()
            
            if not is_valid:
                error_msg = "GitHub configuration validation failed:\n" + "\n".join(f"  - {error}" for error in errors)
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            logger.info("GitHub configuration validation passed")
        else:
            logger.info("GitHub integration is disabled")
        
        logger.info("Configuration validation completed successfully")

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
