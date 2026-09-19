# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
uv sync                                  # dependencies
uv run server.py                         # run the server
uv run --extra test pytest               # the suite (benchmarks are opt-in)
make lint                                # ruff check + ruff format --check

# register with Claude Code
claude mcp add lifecycle $(which uv) -- --directory $(pwd) run server.py
```

`LIFECYCLE_DB` sets the SQLite path (default `./lifecycle.db`); the database is created and migrated on first run.

## Architecture Overview

A Model Context Protocol server for software lifecycle management: requirements, tasks and architecture decisions
(ADRs) tracked in SQLite and linked through one `relationships` table. The handlers define the tools; README.md lists
them and `tests/tool_surface_budget.json` holds the counts, so neither number is repeated here to go stale.

### Core Components

- `server.py` — tool routing, input validation, short-ID resolution, the call log
- `handlers/` — one module per domain, each inheriting `BaseHandler`: `RequirementHandler` (create, edit, status,
  query, trace), `TaskHandler` (create, edit, status, query, plus `sync_github_tasks` when GitHub is on),
  `ArchitectureHandler` (create, edit, status, query), `RecordHandler` (details, delete and comment for any record's
  ID, dispatching to the per-type handlers by ID prefix), `RelationshipHandler` (links and history), `ExportHandler`
  (docs and diagrams), `StatusHandler` (the dashboard)
- `database_manager.py` — connections, pooling, schema initialisation
- `lifecycle-schema.sql` + `migrations.py` — the schema file is the version 0 baseline; every change after it is a
  migration, and new and existing databases take the same migration path. Never edit the baseline to change the
  schema. Each migration runs in one transaction with its `schema_version` row; a failure rolls back and
  `MigrationError` stops the server from starting
- `prompts.py` — the prompts the server offers clients
- `pyproject.toml` — entry point `lifecycle-mcp = "lifecycle_mcp.server:main"`; the only dependency is
  `mcp[cli]>=1.10,<2` (2.x removed the decorator API `server.py` uses)

### Database Structure

- **Requirements**: Central entity with comprehensive metadata including functional requirements, acceptance criteria, business value and `origin`
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

## Rules

- **stdout is the protocol channel**: never `print()` in `src/` (ruff T20 enforces it); log to stderr. `scripts/mcp_handshake_smoke.py` verifies a server end to end
- **Strict tool inputs**: `server.py` adds `additionalProperties: false` to every tool schema, so undeclared fields are refused by name. Declare every new parameter in the tool definition. The server validates calls itself, in `_route_tool_call` under `@server.call_tool(validate_input=False)`: the MCP layer would otherwise refuse them before any of our code ran, leaving the refusal unlogged and its message unimprovable. A type error whose parameter has a close-named sibling that accepts the value names that sibling (`requirement_id` → `requirement_ids`), read from the tool's own schema rather than a list of pairs (roadmap R19)
- **Tool surface budget**: every tool definition costs client context on every request. `tests/test_tool_surface_budget.py` fails when a handler's tool count or `tools/list` definition size exceeds `tests/tool_surface_budget.json`. Adding a tool or parameter means raising that budget in the same change; `uv run python scripts/tool_surface_report.py` shows sizes per handler and tool (roadmap R15)
- **Schema coverage**: `tests/test_schema_coverage.py` fails when a requirements, tasks or architecture column can't be set by that table's create or update tool, or when a tool property has no column. When adding a column, expose it (tool schema, handler, details, export) or put it on the test's explicit system or pending list with the reason
- **GitHub is opt-in**: issues are only created or synced when `LIFECYCLE_GITHUB=on`. `tests/conftest.py` fails any test that spawns `gh` or `git`; tests needing a real repository are marked `github_live` and close their issues via `github_issue_cleanup`
- **Tool errors**: handlers return `_create_error_response(...)`; the server raises it as `ToolCallError` so clients receive `isError=true`
- **Async Architecture**: All handler methods use async/await for MCP protocol compliance
- **A signal that always fires teaches the reader to ignore it** (roadmap R17): creating a record starts its
  verification clock rather than tripping the alarm, the staleness line states only the two times it holds (content
  changed, last checked) and never invents a "stale since", and an empty ready-to-start result says which case it
  is. `WORK_COMPLETE_WHERE` in `requirement_handler.py` is the one definition behind the dashboard's Work Complete,
  Decision Pending section and `query_requirements(work_complete=True)`; neither moves a requirement
- **Changed since last review is derived, not stored**: `changes_since_review()` in `requirement_handler.py` finds field edits after a reviewed requirement's latest status change. The next transition clears it and its comment is the acknowledgement. Don't add a marker column or an acknowledgement tool (owner decision, TASK-0019)

## How It Works

- **Prompts, not conversation tools**: the server serves `prompts/list` and `prompts/get` from `prompts.py`. A prompt
  is text the client's model fills in and passes to a tool, so no session lives on the server, and prompts are a
  separate MCP primitive that costs nothing against the tool budget (roadmap R11). Two are offered:
  `capture_requirement` writes one record, and `reconcile_requirements` compares a transcript, document or codebase
  against the stored set and sorts what it finds into new, amends, already covered and contradicted (roadmap R21).
  Only the first two are applied; a contradiction is reported and never resolved, because a requirement is worth
  storing precisely because it can disagree with the code
- **Where a requirement came from**: `requirements.origin` is `stated`, `derived-from-code` or
  `derived-from-transcript` (migration 18), and only a derived one shows an Origin line in details and export.
  Provenance is a column, not a status: the transition map and its stop statuses are always-on rules (ADR-0004), and
  a derived requirement that arrived already approved would cost the tracker its ability to disagree with the code.
  A derived requirement is created in Draft like any other and waits for the Approved gate (roadmap R21)
- **Workflow rules are configurable**: `LIFECYCLE_RULES` is `off`, `warn` (the default) or `enforce`. A handler collects
  the reasons a status move is risky and passes them to `BaseHandler._rule_warnings`: warn returns them for the
  response text and `structuredContent`, enforce raises `StatusRefused` before anything is written, off checks
  nothing. The always-on rules are deliberately outside it: the Validated gate, R9's Superseded link and the
  requirement transition map (roadmap R8, ADR-0004)
- **Thin records and staleness**: `rules.thin_record_reasons` says which fields a new record of that kind usually
  needs, through the same `_rule_warnings` helper as every other rule. `requirement_handler.verification` derives
  when a requirement was last checked (writing it, then a comment or a status move) and `stale_requirements` lists
  those changed since or unchecked for longer than `rules.stale_after_days()` (`LIFECYCLE_STALE_AFTER`, default 14);
  both read lifecycle events rather than a stored column, and use event ids because timestamps are second-resolution
  (roadmap R11, R17)
- **Editing records**: every update tool goes through `BaseHandler._apply_edit`. It bumps `revision` once, logs a `field_edit` event per changed field, honours `if_revision`, and takes a `check` hook for lifecycle rules (raise `EditRefused`) and a `relink` hook for link changes inside the same transaction. Rules:
  - requirement edits at Approved or later need a reason
  - ADRs are editable only while Proposed. An Accepted one takes a dated `amendment` instead (roadmap R20): it is a
    `lifecycle_events` row of its own kind, never an `UPDATE` on `architecture`, so the decision's text, revision and
    `updated_at` are untouched and "the original is never altered" holds of the stored row rather than the rendering.
    `amendments()` and `format_amendments()` in `architecture_handler.py` render it for both details and export
  - deletes (`BaseHandler._delete_entity`) only remove early-stage records nothing depends on
- **Status tools**: each `_update_*_status` passes a per-record `_change_*_status` to `BaseHandler._change_statuses`,
  which runs it for the single ID or for each ID of the list form (`*_ids`) and builds the response; a per-record
  move raises `StatusRefused` to refuse. Requirement moves follow `requirement_path()`: the shortest path in
  `REQUIREMENT_TRANSITIONS`, never through `REQUIREMENT_STOP_STATUSES` (Approved, Validated), every step in one
  transaction (ADR-0003)
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
- **Call log**: with `LIFECYCLE_CALL_LOG=/path/calls.jsonl` the server appends one JSON line per tool call (tool, argument names, ms, isError, response size; no argument values). Every call the server receives is logged, the refused ones included: `error_kind` is `validation`, `unknown_tool` or `handler`, and `rejected` carries the rule and parameter a schema refusal names — never the value, because jsonschema quotes it in the message. `scripts/tool_usage_report.py` counts refusals apart from handler errors; evidence so far is in `docs/tool-surface/usage-evidence.md`, whose figures predate this and undercount refused calls (roadmap R18)
- **Details show a record's links from its own end**: R9 gave architecture and task details theirs and R23
  added the requirement end, so a requirement with a decision against it and no tasks no longer reads as
  unlinked. A section appears only when it has rows
