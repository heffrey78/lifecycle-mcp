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
   - Exposes 39 tools for lifecycle management across 7 handler modules
   - Uses async architecture for proper MCP protocol compliance
   - Implements clean separation of concerns with handler registry for tool routing
   - Validates state transitions and business rules through domain-specific handlers
   - Maintains backward compatibility while improving maintainability

2. **Handler Architecture** (`src/lifecycle_mcp/handlers/`): Modular async handlers for different domains
   - `BaseHandler`: Abstract base class with common async patterns, utilities, and standardized response formatting
   - `RequirementHandler`: Requirements lifecycle management (8 tools) - create, edit, status, delete, query (text and JSON), details, trace
   - `TaskHandler`: Task creation and progress tracking (7 tools, plus `sync_github_tasks` when GitHub is on) - create, edit, status, delete, query (text and JSON), details
   - `ArchitectureHandler`: ADR management and reviews (8 tools) - create, edit, status, delete, query (text and JSON), details, review
   - `RelationshipHandler`: Links and history (4 tools) - create, delete, query links, entity history
   - `ExportHandler`: Documentation generation (2 tools) - export docs, create diagrams
   - `StatusHandler`: Project health monitoring (2 tools) - project status and metrics

3. **DatabaseManager** (`src/lifecycle_mcp/database_manager.py`): Centralized database operations
   - Manages SQLite database connections and schema initialization
   - Provides async database operations for all handlers
   - Handles database path configuration via LIFECYCLE_DB environment variable
   - Implements connection pooling and error handling

4. **Database Schema** (`src/lifecycle_mcp/lifecycle-schema.sql` + `src/lifecycle_mcp/migrations.py`)
   - `lifecycle-schema.sql` is the version 0 baseline; every change after it is a migration, and new and
     existing databases take the same migration path. Never edit the baseline to change the schema.
   - Each migration runs in one transaction with its `schema_version` row; a failure rolls back and
     `MigrationError` stops the server from starting
   - Requirements, tasks and architecture decisions (ADRs), linked through the `relationships` table
   - Automated triggers for status updates and denormalized metrics

5. **Project Configuration** (`pyproject.toml`): Standard Python packaging
   - Entry point: `lifecycle-mcp = "lifecycle_mcp.server:main"`
   - Minimal dependencies: only `mcp[cli]>=1.10,<2` (2.x removed the decorator API `server.py` uses)
   - Development dependencies for testing and linting

### Key Design Patterns

- **Async Handler Architecture**: All MCP tool handlers use async/await patterns for proper protocol compliance
- **Entity Lifecycle States**: Requirements follow Draft → Under Review → Approved → Architecture → Ready → Implemented → Validated → Deprecated
- **Hierarchical Task Structure**: Tasks can have parent-child relationships with automatic numbering (TASK-XXXX-YY-ZZ)
- **Requirement Traceability**: Many-to-many relationships link requirements to tasks and architecture decisions
- **Event Logging**: Automatic logging of status changes, per-field edits (before, after, actor, reason) and lifecycle events
- **Denormalized Metrics**: Task counts and completion percentages stored directly on requirements for performance
- **Modular Handlers**: Domain-specific handlers inherit from `BaseHandler` with common async utilities

### Database Structure

- **Requirements**: Central entity with comprehensive metadata including functional requirements, acceptance criteria, business value
- **Tasks**: Implementation work items linked to requirements with effort estimation and assignee tracking
- **Architecture**: ADRs and technical design documents with decision drivers and consequences
- **Relationships**: the `relationships` table is the only place links are stored (migration 8 removed the old
  `requirement_tasks`, `requirement_architecture`, `task_dependencies`, `requirement_dependencies` tables and
  `tasks.parent_task_id`). Write links with `BaseHandler._link()`. Direction conventions: requirement → task
  (`implements`), requirement → architecture (`addresses`), child → parent (`parent`), dependent → dependency
  (`depends`/`requires`/`informs`), blocker → blocked (`blocks`). `create_relationship` normalizes reversed
  requirement links.
- **Views**: requirement_progress, task_hierarchy, blocked_items, requirement_hierarchy (all over `relationships`)
- **Triggers on relationships**: keep `requirements.task_count`/`tasks_completed` current and enforce requirement
  decomposition depth and no circular parents

### MCP Tools Available

The server exposes 39 tools across 7 handler modules:

**Requirement Management (8 tools):**
- `create_requirement` - Create new requirements with validation
- `update_requirement` - Edit content in place; reason required at Approved or later
- `update_requirement_status` - Move requirements through lifecycle with state validation
- `delete_requirement` - Delete an unlinked Draft requirement
- `query_requirements` / `query_requirements_json` - Search and filter requirements (text or JSON)
- `get_requirement_details` - Full requirement information with relationships
- `trace_requirement` - Full lifecycle traceability

**Task Management (7 tools, plus 1 when GitHub is on):**
- `create_task` - Create tasks linked to requirements
- `update_task` - Edit content, move to another parent, replace requirement links
- `update_task_status` - Update task progress
- `delete_task` - Delete a Not Started task nothing depends on
- `query_tasks` / `query_tasks_json` - Search and filter tasks (text or JSON)
- `get_task_details` - Complete task information
- `sync_github_tasks` - Sync one task or every linked task from GitHub issues (listed only when `LIFECYCLE_GITHUB=on`)

**Architecture Management (8 tools):**
- `create_architecture_decision` - Record ADRs
- `update_architecture` - Edit content while Proposed
- `update_architecture_status` - Update ADR status
- `delete_architecture` - Delete an unlinked Proposed ADR
- `query_architecture_decisions` / `query_architecture_decisions_json` - Search architecture decisions (text or JSON)
- `get_architecture_details` - Full ADR information
- `add_architecture_review` - Add review comments

**Relationships and History (4 tools):**
- `create_relationship` / `delete_relationship` - Add or remove a link
- `query_relationships` - One record's links (by direction and type) or every link as JSON
- `get_entity_history` - Creation, field edits, status changes, comments and deletion for one record

**Documentation Export (2 tools):**
- `export_project_documentation` - Generate project docs
- `create_architectural_diagrams` - Generate architecture diagrams

**Status Monitoring (2 tools):**
- `get_project_status` - Project health dashboard
- `get_project_metrics` - Structured metrics

### Database Environment

The server uses the `LIFECYCLE_DB` environment variable to specify the SQLite database path (defaults to "./lifecycle.db"). The database is automatically initialized with the schema on first run.

## Important Notes

- **Async Architecture**: All handler methods use async/await for MCP protocol compliance
- **stdout is the protocol channel**: never `print()` in `src/` (ruff T20 enforces it); log to stderr. `scripts/mcp_handshake_smoke.py` verifies a server end to end
- **GitHub is opt-in**: issues are only created or synced when `LIFECYCLE_GITHUB=on`. `tests/conftest.py` fails any test that spawns `gh` or `git`; tests needing a real repository are marked `github_live` and close their issues via `github_issue_cleanup`
- **Tool errors**: handlers return `_create_error_response(...)`; the server raises it as `ToolCallError` so clients receive `isError=true`
- **Strict tool inputs**: `server.py` adds `additionalProperties: false` to every tool schema, so undeclared fields are refused by name. Declare every new parameter in the tool definition
- **Editing records**: every update tool goes through `BaseHandler._apply_edit`. It bumps `revision` once, logs a `field_edit` event per changed field, honours `if_revision`, and takes a `check` hook for lifecycle rules (raise `EditRefused`) and a `relink` hook for link changes inside the same transaction. Rules:
  - requirement edits at Approved or later need a reason
  - ADRs are editable only while Proposed
  - deletes (`BaseHandler._delete_entity`) only remove early-stage records nothing depends on
- **Changed since last review is derived, not stored**: `changes_since_review()` in `requirement_handler.py` finds field edits after a reviewed requirement's latest status change. The next transition clears it and its comment is the acknowledgement. Don't add a marker column or an acknowledgement tool (owner decision, TASK-0019)
- **Schema coverage**: `tests/test_schema_coverage.py` fails when a requirements, tasks or architecture column can't be set by that table's create or update tool, or when a tool property has no column. When adding a column, expose it (tool schema, handler, details, export) or put it on the test's explicit system or pending list with the reason
- **Tool surface budget**: every tool definition costs client context on every request. `tests/test_tool_surface_budget.py` fails when a handler's tool count or `tools/list` definition size exceeds `tests/tool_surface_budget.json`. Adding a tool or parameter means raising that budget in the same change; `uv run python scripts/tool_surface_report.py` shows sizes per handler and tool (roadmap R15)
- **Call log**: with `LIFECYCLE_CALL_LOG=/path/calls.jsonl` the server appends one JSON line per tool call (tool, argument names, ms, isError, response size; no argument values). `scripts/tool_usage_report.py` summarises logs; evidence so far is in `docs/tool-surface/usage-evidence.md`
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