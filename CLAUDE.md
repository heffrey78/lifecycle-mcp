# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Installation and Setup

#### Using uv (Recommended - No Installation Required!)
```bash
# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies
uv sync
```

#### Using pip (Traditional)
```bash
pip install -e .
```

### Running the MCP Server

#### With uv (Recommended)
```bash
uv run server.py
```

#### With pip installation
```bash
lifecycle-mcp
```

### Testing the Server
```bash
# Test with Claude Code (uv method - recommended)
claude mcp add lifecycle $(which uv) -- --directory $(pwd) run server.py

# Test with Claude Code (pip method)
claude mcp add lifecycle lifecycle-mcp

# Manual configuration for other MCP clients
export LIFECYCLE_DB="./lifecycle.db"
uv run server.py  # or lifecycle-mcp if installed with pip
```

## Architecture Overview

This is a Model Context Protocol (MCP) server for software lifecycle management. The system provides structured tracking of requirements, tasks, and architecture decisions through a SQLite database.

### Core Components

1. **LifecycleMCPServer** (`src/lifecycle_mcp/server.py`): Refactored main server using modular handler architecture
   - Exposes 22 tools for lifecycle management across 6 handler modules
   - Uses async architecture for proper MCP protocol compliance
   - Implements clean separation of concerns with handler registry for tool routing
   - Validates state transitions and business rules through domain-specific handlers
   - Maintains backward compatibility while improving maintainability

2. **Handler Architecture** (`src/lifecycle_mcp/handlers/`): Modular async handlers for different domains
   - `BaseHandler`: Abstract base class with common async patterns, utilities, and standardized response formatting
   - `RequirementHandler`: Requirements lifecycle management (5 tools) - create, update, query, details, trace
   - `TaskHandler`: Task creation and progress tracking (4 tools) - create, update, query, details
   - `ArchitectureHandler`: ADR management and reviews (5 tools) - create, update, query, details, review
   - `InterviewHandler`: Interactive requirement gathering (4 tools) - start/continue interviews and conversations
   - `ExportHandler`: Documentation generation (2 tools) - export docs, create diagrams
   - `StatusHandler`: Project health monitoring (2 tools) - project status and metrics

3. **DatabaseManager** (`src/lifecycle_mcp/database_manager.py`): Centralized database operations
   - Manages SQLite database connections and schema initialization
   - Provides async database operations for all handlers
   - Handles database path configuration via LIFECYCLE_DB environment variable
   - Implements connection pooling and error handling

4. **Database Schema** (`src/lifecycle_mcp/lifecycle-schema.sql`): Comprehensive SQLite schema
   - Requirements table with full lifecycle states and metadata
   - Tasks table with hierarchical structure and effort tracking
   - Architecture decisions (ADRs) tracking with decision drivers
   - Many-to-many relationships for full traceability between entities
   - Automated triggers for status updates and denormalized metrics

5. **Project Configuration** (`pyproject.toml`): Standard Python packaging
   - Entry point: `lifecycle-mcp = "lifecycle_mcp.server:main"`
   - Minimal dependencies: only `mcp>=1.0.0`
   - Development dependencies for testing and linting

### Key Design Patterns

- **Async Handler Architecture**: All MCP tool handlers use async/await patterns for proper protocol compliance
- **Entity Lifecycle States**: Requirements follow Draft → Under Review → Approved → Architecture → Ready → Implemented → Validated → Deprecated
- **Hierarchical Task Structure**: Tasks can have parent-child relationships with automatic numbering (TASK-XXXX-YY-ZZ)
- **Requirement Traceability**: Many-to-many relationships link requirements to tasks and architecture decisions
- **Event Logging**: Automatic logging of status changes and lifecycle events
- **Denormalized Metrics**: Task counts and completion percentages stored directly on requirements for performance
- **Modular Handlers**: Domain-specific handlers inherit from `BaseHandler` with common async utilities

### Database Structure

- **Requirements**: Central entity with comprehensive metadata including functional requirements, acceptance criteria, business value
- **Tasks**: Implementation work items linked to requirements with effort estimation and assignee tracking
- **Architecture**: ADRs and technical design documents with decision drivers and consequences
- **Relationships**: requirement_tasks, requirement_architecture, task_dependencies tables provide full traceability
- **Views**: requirement_progress, task_hierarchy, blocked_items provide common query patterns

### MCP Tools Available

The server exposes 22 tools across 6 handler modules:

**Requirement Management (5 tools):**
- `create_requirement` - Create new requirements with validation
- `update_requirement_status` - Move requirements through lifecycle with state validation
- `query_requirements` - Search and filter requirements
- `get_requirement_details` - Full requirement information with relationships
- `trace_requirement` - Full lifecycle traceability

**Task Management (4 tools):**
- `create_task` - Create tasks linked to requirements
- `update_task_status` - Update task progress
- `query_tasks` - Search and filter tasks
- `get_task_details` - Complete task information

**Architecture Management (5 tools):**
- `create_architecture_decision` - Record ADRs
- `update_architecture_status` - Update ADR status
- `query_architecture_decisions` - Search architecture decisions
- `get_architecture_details` - Full ADR information
- `add_architecture_review` - Add review comments

**Interactive Interviews (4 tools):**
- `start_requirement_interview` - Begin requirement gathering
- `continue_requirement_interview` - Continue interview process
- `start_architectural_conversation` - Begin architecture discussion
- `continue_architectural_conversation` - Continue architecture discussion

**Documentation Export (2 tools):**
- `export_project_documentation` - Generate project docs
- `create_architectural_diagrams` - Generate architecture diagrams

**Status Monitoring (2 tools):**
- `get_project_status` - Project health dashboard

### Database Environment

The server uses the `LIFECYCLE_DB` environment variable to specify the SQLite database path (defaults to "./lifecycle.db"). The database is automatically initialized with the schema on first run.

## Important Notes

- **Async Architecture**: All handler methods use async/await for MCP protocol compliance
- The server implements strict state transition validation for requirements
- All entities use structured ID formats (REQ-XXXX-TYPE-VV, TASK-XXXX-YY-ZZ, ADR-XXXX)
- JSON fields are used extensively for structured data (arrays, objects)
- Automatic triggers maintain denormalized counters and timestamps
- The system is designed for integration with Claude Code and other MCP clients

## Troubleshooting

### "Connection closed" Errors
If you encounter "MCP error -32000: Connection closed", ensure:
1. All handler `handle_tool_call` methods are properly async
2. Server properly awaits handler calls
3. If using pip: Package is installed with `pip install -e .`
4. Re-add server with the appropriate command:
   - uv method: `claude mcp add lifecycle $(which uv) -- --directory $(pwd) run server.py`
   - pip method: `claude mcp add lifecycle lifecycle-mcp`