# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Installation and Setup
```bash
pip install -e .
```

### Running the MCP Server
```bash
lifecycle-mcp
```

### Testing the Server
```bash
# Test with Claude Code
claude mcp add lifecycle-mcp

# Manual configuration for other MCP clients
export LIFECYCLE_DB="./lifecycle.db"
lifecycle-mcp
```

## Architecture Overview

This is a Model Context Protocol (MCP) server for software lifecycle management. The system provides structured tracking of requirements, tasks, and architecture decisions through a SQLite database.

### Core Components

1. **MCP Server** (`src/lifecycle_mcp/server.py`): Main server implementation using the `mcp` library
   - Exposes 11 tools for lifecycle management
   - Handles database operations and tool routing
   - Validates state transitions and business rules

2. **Database Schema** (`src/lifecycle_mcp/lifecycle-schema.sql`): Comprehensive SQLite schema
   - Requirements table with full lifecycle states
   - Tasks table with hierarchical structure
   - Architecture decisions (ADRs) tracking
   - Many-to-many relationships for traceability
   - Automated triggers for status updates and metrics

3. **Project Configuration** (`pyproject.toml`): Standard Python packaging
   - Entry point: `lifecycle-mcp = "lifecycle_mcp.server:main"`
   - Minimal dependencies: only `mcp>=1.0.0`

### Key Design Patterns

- **Entity Lifecycle States**: Requirements follow Draft → Under Review → Approved → Architecture → Ready → Implemented → Validated → Deprecated
- **Hierarchical Task Structure**: Tasks can have parent-child relationships with automatic numbering (TASK-XXXX-YY-ZZ)
- **Requirement Traceability**: Many-to-many relationships link requirements to tasks and architecture decisions
- **Event Logging**: Automatic logging of status changes and lifecycle events
- **Denormalized Metrics**: Task counts and completion percentages stored directly on requirements for performance

### Database Structure

- **Requirements**: Central entity with comprehensive metadata including functional requirements, acceptance criteria, business value
- **Tasks**: Implementation work items linked to requirements with effort estimation and assignee tracking
- **Architecture**: ADRs and technical design documents with decision drivers and consequences
- **Relationships**: requirement_tasks, requirement_architecture, task_dependencies tables provide full traceability
- **Views**: requirement_progress, task_hierarchy, blocked_items provide common query patterns

### MCP Tools Available

The server exposes these tools to MCP clients:
- `create_requirement` - Create new requirements with validation
- `update_requirement_status` - Move requirements through lifecycle with state validation
- `query_requirements` - Search and filter requirements
- `create_task` - Create tasks linked to requirements
- `update_task_status` - Update task progress
- `create_architecture_decision` - Record ADRs
- `get_requirement_details` - Full requirement information with relationships
- `get_project_status` - Project health dashboard
- `trace_requirement` - Full lifecycle traceability
- `get_task_details` - Complete task information
- `query_tasks` - Search and filter tasks

### Database Environment

The server uses the `LIFECYCLE_DB` environment variable to specify the SQLite database path (defaults to "./lifecycle.db"). The database is automatically initialized with the schema on first run.

## Important Notes

- The server implements strict state transition validation for requirements
- All entities use structured ID formats (REQ-XXXX-TYPE-VV, TASK-XXXX-YY-ZZ, ADR-XXXX)
- JSON fields are used extensively for structured data (arrays, objects)
- Automatic triggers maintain denormalized counters and timestamps
- The system is designed for integration with Claude Code and other MCP clients