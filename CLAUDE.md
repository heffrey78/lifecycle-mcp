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
   - Exposes 23 tools (24 with `LIFECYCLE_GITHUB=on`) across 7 handler modules
   - Uses async architecture for proper MCP protocol compliance
   - Implements clean separation of concerns with handler registry for tool routing
   - Validates state transitions and business rules through domain-specific handlers
   - Maintains backward compatibility while improving maintainability

2. **Handler Architecture** (`src/lifecycle_mcp/handlers/`): Modular async handlers for different domains
   - `BaseHandler`: Abstract base class with common async patterns, utilities, and standardized response formatting
   - `RequirementHandler`: Requirements lifecycle management (5 tools) - create, edit, status, query, trace
   - `TaskHandler`: Task creation and progress tracking (4 tools, plus `sync_github_tasks` when GitHub is on) - create, edit, status, query
   - `ArchitectureHandler`: ADR management (4 tools) - create, edit, status, query
   - `RecordHandler`: Operations that take any record's ID (3 tools) - details, delete, comment; dispatches to the per-type handlers by ID prefix
   - `RelationshipHandler`: Links and history (4 tools) - create, delete, query links, entity history
   - `ExportHandler`: Documentation generation (2 tools) - export docs, create diagrams
   - `StatusHandler`: Project health monitoring (1 tool) - project status, with metrics as structured data

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
- **Tasks**: Implementation work items linked to requirements with effort estimation and assignee tracking, and a
  `blocked_reason` that only `update_task_status` writes (migration 15). A task waits on the tasks it depends on or
  requires and on the tasks that block it: `TASK_DEPENDENCIES_SQL` in `task_handler.py` feeds the ready filter,
  task details and the dashboard
- **Architecture**: ADRs and technical design documents with decision drivers and consequences
- **Relationships**: the `relationships` table is the only place links are stored (migration 8 removed the old
  `requirement_tasks`, `requirement_architecture`, `task_dependencies`, `requirement_dependencies` tables and
  `tasks.parent_task_id`). Write links with `BaseHandler._link()`. Direction conventions: requirement → task
  (`implements`), requirement → architecture (`addresses`), child → parent (`parent`), dependent → dependency
  (`depends`/`requires`/`informs`), blocker → blocked (`blocks`), task → architecture (`implements`), newer →
  older architecture (`supersedes`). `create_relationship` normalizes reversed requirement and task/ADR links;
  a `supersedes` link also moves the older ADR to Superseded in the same transaction (ADR-0003).
- **Views**: requirement_progress, task_hierarchy, blocked_items, requirement_hierarchy (all over `relationships`)
- **Triggers on relationships**: keep `requirements.task_count`/`tasks_completed` current, keep
  `architecture.superseded_by` equal to the incoming `supersedes` link (migration 14) and refuse circular parents

### MCP Tools Available

The server exposes 23 tools (24 with `LIFECYCLE_GITHUB=on`) across 7 handler modules:

**Requirement Management (5 tools):**
- `create_requirement` - Create new requirements with validation
- `update_requirement` - Edit content in place; reason required at Approved or later
- `update_requirement_status` - Move one or many requirements; walks the allowed path, never through Approved or Validated
- `query_requirements` - Search and filter requirements, or list those whose work is done and only the decision is missing (text list plus structured records)
- `trace_requirement` - Full lifecycle traceability

**Task Management (4 tools, plus 1 when GitHub is on):**
- `create_task` - Create tasks linked to requirements
- `update_task` - Edit content, move to another parent, replace requirement links
- `update_task_status` - Update progress of one or many tasks; a Blocked comment is kept as the reason
- `query_tasks` - Search and filter tasks, or list those ready to start (text list plus structured records)
- `sync_github_tasks` - Sync one task or every linked task from GitHub issues (listed only when `LIFECYCLE_GITHUB=on`)

**Architecture Management (4 tools):**
- `create_architecture_decision` - Record ADRs
- `update_architecture` - Edit content while Proposed
- `update_architecture_status` - Update status of one or many ADRs; Superseded needs a supersedes link
- `query_architecture_decisions` - Search architecture decisions (text list plus structured records)

**Any Record (3 tools):**
- `get_details` - Full details of a requirement, task or ADR by ID, with links and comments
- `delete_record` - Delete an unlinked Draft requirement, Not Started task or Proposed ADR
- `add_comment` - Comment on any record; shown in details and history

**Relationships and History (4 tools):**
- `create_relationship` / `delete_relationship` - Add or remove a link
- `query_relationships` - One record's links (by direction and type) or every link as JSON
- `get_entity_history` - Creation, field edits, status changes, comments and deletion for one record

**Documentation Export (2 tools):**
- `export_project_documentation` - Generate project docs
- `create_architectural_diagrams` - Mermaid diagrams drawn from the stored links

**Status Monitoring (1 tool):**
- `get_project_status` - Project health dashboard with every blocked or waiting item, the requirements whose work is done and those needing verification, with metrics as structured data

### Database Environment

The server uses the `LIFECYCLE_DB` environment variable to specify the SQLite database path (defaults to "./lifecycle.db"). The database is automatically initialized with the schema on first run.

## Important Notes

- **Async Architecture**: All handler methods use async/await for MCP protocol compliance
- **stdout is the protocol channel**: never `print()` in `src/` (ruff T20 enforces it); log to stderr. `scripts/mcp_handshake_smoke.py` verifies a server end to end
- **GitHub is opt-in**: issues are only created or synced when `LIFECYCLE_GITHUB=on`. `tests/conftest.py` fails any test that spawns `gh` or `git`; tests needing a real repository are marked `github_live` and close their issues via `github_issue_cleanup`
- **Prompts, not conversation tools**: the server serves `prompts/list` and `prompts/get` from `prompts.py`. A prompt
  is text the client's model fills in and passes to a tool, so no session lives on the server, and prompts are a
  separate MCP primitive that costs nothing against the tool budget (roadmap R11)
- **Thin records and staleness**: `rules.thin_record_reasons` says which fields a new record of that kind usually
  needs, through the same `_rule_warnings` helper as every other rule. `requirement_handler.verification` derives
  when a requirement was last checked (writing it, then a comment or a status move) and `stale_requirements` lists
  those changed since or unchecked for longer than `rules.stale_after_days()` (`LIFECYCLE_STALE_AFTER`, default 14);
  both read lifecycle events rather than a stored column, and use event ids because timestamps are second-resolution
  (roadmap R11, R17)
- **A signal that always fires teaches the reader to ignore it** (roadmap R17): creating a record starts its
  verification clock rather than tripping the alarm, the staleness line states only the two times it holds (content
  changed, last checked) and never invents a "stale since", and an empty ready-to-start result says which case it
  is. `WORK_COMPLETE_WHERE` in `requirement_handler.py` is the one definition behind the dashboard's Work Complete,
  Decision Pending section and `query_requirements(work_complete=True)`; neither moves a requirement
- **Workflow rules are configurable**: `LIFECYCLE_RULES` is `off`, `warn` (the default) or `enforce`. A handler collects
  the reasons a status move is risky and passes them to `BaseHandler._rule_warnings`: warn returns them for the
  response text and `structuredContent`, enforce raises `StatusRefused` before anything is written, off checks
  nothing. The always-on rules are deliberately outside it: the Validated gate, R9's Superseded link and the
  requirement transition map (roadmap R8, ADR-0004)
- **Short IDs**: `short_ids.resolve_arguments` runs in `server._route_tool_call`, so every tool takes `REQ-12-FUNC`,
  `TASK-12`, `TASK-12-1` or `ADR-4` and no handler knows about aliases. A complete stored ID is never treated as an
  alias: it reaches the handler untouched even when no such record exists, so "not found" messages, per-ID results
  from list calls and empty query results stay the handler's to give (roadmap R14)
- **Requirement progress counts leaf tasks**: a task that something points at as its parent is counted through its
  subtasks, not again on its own. The counter triggers carry that rule and migration 16 recomputes existing rows
  (F-22, roadmap R14)
- **Evidence rides on the status move**: `update_task_status` keeps `commit` and `evidence` on the task in
  `commit_ref` and `evidence` (migration 17), as it keeps a Blocked comment in `blocked_reason`. Omitting them
  leaves the stored values alone. Export carries them, and carries every record's comments (roadmap R12)
- **Tool errors**: handlers return `_create_error_response(...)`; the server raises it as `ToolCallError` so clients receive `isError=true`
- **Strict tool inputs**: `server.py` adds `additionalProperties: false` to every tool schema, so undeclared fields are refused by name. Declare every new parameter in the tool definition. The server validates calls itself, in `_route_tool_call` under `@server.call_tool(validate_input=False)`: the MCP layer would otherwise refuse them before any of our code ran, leaving the refusal unlogged and its message unimprovable. A type error whose parameter has a close-named sibling that accepts the value names that sibling (`requirement_id` → `requirement_ids`), read from the tool's own schema rather than a list of pairs (roadmap R19)
- **Editing records**: every update tool goes through `BaseHandler._apply_edit`. It bumps `revision` once, logs a `field_edit` event per changed field, honours `if_revision`, and takes a `check` hook for lifecycle rules (raise `EditRefused`) and a `relink` hook for link changes inside the same transaction. Rules:
  - requirement edits at Approved or later need a reason
  - ADRs are editable only while Proposed
  - deletes (`BaseHandler._delete_entity`) only remove early-stage records nothing depends on
- **Status tools**: each `_update_*_status` passes a per-record `_change_*_status` to `BaseHandler._change_statuses`,
  which runs it for the single ID or for each ID of the list form (`*_ids`) and builds the response; a per-record
  move raises `StatusRefused` to refuse. Requirement moves follow `requirement_path()`: the shortest path in
  `REQUIREMENT_TRANSITIONS`, never through `REQUIREMENT_STOP_STATUSES` (Approved, Validated), every step in one
  transaction (ADR-0003)
- **Changed since last review is derived, not stored**: `changes_since_review()` in `requirement_handler.py` finds field edits after a reviewed requirement's latest status change. The next transition clears it and its comment is the acknowledgement. Don't add a marker column or an acknowledgement tool (owner decision, TASK-0019)
- **Schema coverage**: `tests/test_schema_coverage.py` fails when a requirements, tasks or architecture column can't be set by that table's create or update tool, or when a tool property has no column. When adding a column, expose it (tool schema, handler, details, export) or put it on the test's explicit system or pending list with the reason
- **Tool surface budget**: every tool definition costs client context on every request. `tests/test_tool_surface_budget.py` fails when a handler's tool count or `tools/list` definition size exceeds `tests/tool_surface_budget.json`. Adding a tool or parameter means raising that budget in the same change; `uv run python scripts/tool_surface_report.py` shows sizes per handler and tool (roadmap R15)
- **Call log**: with `LIFECYCLE_CALL_LOG=/path/calls.jsonl` the server appends one JSON line per tool call (tool, argument names, ms, isError, response size; no argument values). Every call the server receives is logged, the refused ones included: `error_kind` is `validation`, `unknown_tool` or `handler`, and `rejected` carries the rule and parameter a schema refusal names — never the value, because jsonschema quotes it in the message. `scripts/tool_usage_report.py` counts refusals apart from handler errors; evidence so far is in `docs/tool-surface/usage-evidence.md`, whose figures predate this and undercount refused calls (roadmap R18)
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