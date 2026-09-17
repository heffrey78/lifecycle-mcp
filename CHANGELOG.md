# Changelog

## Unreleased

### Errors that explain themselves, and a call log that sees them (roadmap R18, R19)

Both findings came out of the linkcheck dogfooding run, and both had one cause. Schema validation ran in the MCP
layer, before any of this server's code, so a call it refused left no trace in `LIFECYCLE_CALL_LOG` and its message
could not be improved. That run ended with 9 errors in the server log against 11 in the client's, and the two the
server could not see were the two where the client got the interface wrong - the most informative signal the log
could carry (F-53). One of them cost about 5% of the run's total tool traffic: a list passed to `requirement_id` was
refused with `['REQ-1-FUNC', ...] is not of type 'string'`, which names the value and never mentions that
`requirement_ids` sits one character away, and sent the run writing up a defect that did not exist (F-54).

#### Added
- A type error on a parameter whose schema has a near neighbour accepting the value names that neighbour: passing a
  list to `requirement_id` now answers that `requirement_id` takes a string and `requirement_ids` takes an array and
  accepts what you passed. The neighbour is read from the tool's own schema rather than a list of known pairs, so a
  new singular/plural pair is covered the day it is declared. A type error with no such neighbour is unchanged.
- Every call the server receives reaches the call log, including one its schema refused and one naming a tool that
  does not exist. Those carry `error_kind` (`validation`, `unknown_tool` or `handler`) and `rejected`, the rule and
  parameter the refusal names - never the value, because jsonschema quotes it in the message and the log has never
  held argument values.
- `scripts/tool_usage_report.py` counts calls refused before a handler ran apart from handler errors, names the
  tools attracting them, and prints both totals so they can be seen to add up.

#### Changed
- The server validates tool input itself, in `_route_tool_call` under `@server.call_tool(validate_input=False)`,
  against the same schemas `tools/list` serves and in the same order as before: after the tool is resolved, before
  short IDs are.
- `docs/tool-surface/usage-evidence.md` records that every figure on it undercounts refused calls. Both sessions it
  covers predate this change, and the logs that would re-derive them cannot be recovered.

### Fields that get filled, and requirements that stay fresh (roadmap R11)

The interview tools R16 removed are not coming back. Measured in this project's own tracker, guided questioning was
never the gap: every requirement had its core filled by calling `create_requirement` directly. What was missing sat
one field-set down - `validation_metrics` set on 0 of 18 requirements, `business_rules` and
`nonfunctional_requirements` likewise, `definition_of_done` on 0 of 69 tasks - and requirements drifted, six of them
needing their current state re-checked against the code. The tool count stays 23.

#### Added
- `create_requirement` says when a requirement has no `acceptance_criteria`, and when an NFUNC requirement has no
  `validation_metrics`; `create_task` says when a P0 or P1 task has no `test_plan`. These go through the R8
  workflow rules, so `LIFECYCLE_RULES=enforce` refuses before anything is written and `off` says nothing.
- The server answers `prompts/list` and `prompts/get`, which it never did before, and offers `capture_requirement`:
  a guide the client's own model fills in and passes to `create_requirement` in one call. No session is kept on the
  server, so nothing is lost on restart, and prompts are a separate MCP primitive, so this costs nothing against the
  tool budget.
- A requirement's details say when it was last checked against reality - Last Verified, Never verified, or Stale
  since - and the dashboard lists the requirements whose content changed after anyone last looked. A comment or a
  status move counts as checking it. Like Changed Since Last Review, this is derived rather than stored, but it
  covers Draft requirements too.

#### Removed
- The LLM sampling code, 791 lines that could never run: nothing ever called `set_mcp_client`, so requirement
  analysis, the clarification and decomposition responses and the ADR diagram suggestions all returned early.
  `llm_decomposition_prompts.py`, which nothing imported, goes with them. `create_requirement` and
  `create_architecture_decision` behave exactly as before.

### Evidence on tasks, and fuller exports (roadmap R12)

Test results, commits and files had no structured home, so evidence went into free-text comments - "21 tests
passing" in a comment was how the lab session recorded it - and `export_project_documentation` left comments out
entirely, so a hand-off document lost the reasoning behind the work (F-26, F-31). The tool count stays 23;
definitions go from 12,580 to 12,749 characters.

#### Added
- `update_task_status` takes an optional `commit` and an optional `evidence` summary and keeps them on the task,
  the way the comment on a move to Blocked is kept as its reason. A later move that omits them leaves them in
  place, so the record of why a task is Complete survives; passing new values replaces them. Both show in the
  task's details. Migration 17 adds the two columns.
- Exported task documentation carries a task's commit and evidence, and all three exported files carry the
  comments stored against their records.

### Short IDs and honest progress (roadmap R14)

#### Added
- Every tool that takes a record ID also accepts a short form, so the zero padding and the trailing version can be
  left out: `REQ-12-FUNC` for `REQ-0012-FUNC-00`, `TASK-12` for `TASK-0012-00-00`, `TASK-12-1` for
  `TASK-0012-01-00`, `ADR-4` for `ADR-0004`. A requirement's alias keeps its type because numbers repeat across
  types: `REQ-12` alone can be four different records. Full stored IDs work exactly as before, an alias matching
  nothing is refused as unknown, and one matching several is refused naming the candidates rather than guessing.
  Resolution happens once in the server's routing, so no tool gained a parameter and the surface is unchanged.

#### Fixed
- Requirement progress counted a parent task and its subtasks separately, so a requirement whose one task was split
  in two read three tasks (F-22). A task that something points at as its parent is now counted through its
  subtasks. Migration 16 rebuilds the counter triggers and recomputes `task_count` and `tasks_completed` on existing
  databases, touching no status.

### Diagrams that show structure (roadmap R13)

Diagrams drew inventories: boxes hung off category nodes, at most 20 edges and only requirement-to-task ones, with
the first 10 requirements, 10 tasks and 5 decisions kept and the rest dropped without a word (F-16). They now draw
the graph that is actually in `relationships`. The tool count stays 23; definitions go from 12,512 to 12,580
characters.

**Breaking:**
- Diagram files have stable names: `{diagram_type}-diagram.mmd` or `.md`, overwritten on each render. They used to
  carry a timestamp and pile up in `exports/` (F-17). Anything matching the old names needs updating.
- `directory_structure` is removed. It returned a hard-coded `src/docs/tests` stub unrelated to the project, and is
  now refused like any other unknown diagram type.
- Edges read source to target with a label, one rule across every diagram, so a dependency points at what it waits
  on. The dependencies and tasks diagrams used to draw the reverse, unlabelled.

#### Added
- `full_project` draws requirement-implements-task, requirement-addresses-ADR, task-implements-ADR and
  ADR-supersedes-ADR edges. The architecture diagram shows supersession and the requirements each decision serves;
  the requirements diagram adds parent and depends edges; the tasks diagram adds subtask, dependency and blocks
  edges; the dependencies diagram names tasks instead of bare IDs.
- `limit` caps each kind of record. The response says what was drawn and what the limit left out, so nothing goes
  missing quietly. Without it nothing is capped.
- Deprecated requirements and decisions are left out by default and counted in the response.
- Node labels keep 60 characters of the title and escape the quotes and brackets that used to break mermaid.

### Configurable workflow rules (roadmap R8, ADR-0004)

`LIFECYCLE_RULES` chooses `off`, `warn` or `enforce`. **warn is the default**: every call keeps the outcome it has
today, and a risky status move only gains an explanation, in the response text and in `structuredContent` under
`warnings` (per record for a list of IDs). `enforce` refuses the move before anything is written; `off` checks
nothing. An unrecognised value falls back to `warn`. The tool count stays 23 and definitions are unchanged.

#### Added
- Task rules: starting or completing a task whose dependencies are not all Complete names them; an abandoned
  dependency is named separately, with the two ways out (drop the link, or abandon the waiting task); completing a
  task while a subtask is open names the open subtasks; completing a task that was never started or is still
  Blocked, and reopening a Complete task, each say so.
- A requirement reaching Implemented while the tasks implementing it are open names them.
- An architecture decision moving outside its vocabulary says where that status usually goes, with the ADR statuses
  and the TDD chain as separate sets.
- The dashboard and a task's details name abandoned dependencies instead of listing them as ordinary waits;
  `structuredContent` carries them under `abandoned_dependencies`.

#### Unchanged
- Three rules apply whatever the mode, because they protect what the server maintains itself: the Validated gate,
  the `supersedes` link behind Superseded, and the requirement transition map.

### What to work on next (roadmap R7)

The server still lists 23 tools; definitions grow from 12,341 to 12,512 characters.

#### Added
- `query_tasks` takes `ready: true` for Not Started tasks whose dependencies are all Complete, highest priority
  first. A task waits on the tasks it depends on or requires, and on the tasks that block it.
- `get_details` on a task lists Depends On and Blocks.
- The comment given with a move to Blocked is kept as the task's blocked reason until it leaves Blocked, and
  `get_details` shows it. Migration 15 adds `tasks.blocked_reason`.

#### Changed
- `get_project_status` lists every Blocked task with its reason, and every task or requirement still waiting on a
  dependency with what it waits on. Blocked tasks without dependency links used to be missing, and the list was cut
  at 10. `structuredContent` carries the list under `blocked`.
- `query_tasks` filters combine: `requirement_id` no longer ignores `status`, `priority` and `assignee`.

### Bulk status moves and design links (roadmap R9, ADR-0003)

Status changes were about half of all tool calls, one record and one step at a time. They now take one call. The
server still lists 23 tools; definitions grow from 11,815 to 12,341 characters.

#### Added
- `update_requirement_status`, `update_task_status` and `update_architecture_status` accept `requirement_ids`,
  `task_ids` or `architecture_ids` instead of the single ID. Each ID moves on its own, and `structuredContent` holds
  `results` (one entry per ID, with `error` when refused), `moved` and `refused`. Some refusals make it a warning
  while the other IDs still move; it is an error only when none moved.
- `update_requirement_status` walks the allowed path when `new_status` is more than one step away, logging each step:
  Draft to Approved goes through Under Review. A move never passes through Approved or Validated, and a gate on the
  way refuses the whole move. Multi-step results include `path`.
- `create_relationship` accepts `implements` between a task and an architecture decision, in either order, and
  `supersedes` from a newer decision to an older one. Superseding moves the older decision to Superseded and sets its
  `superseded_by`.
- `get_details` shows the tasks implementing a decision, the decisions a task implements, and what a decision
  supersedes or is superseded by.

#### Changed
- `update_architecture_status` refuses Superseded unless a `supersedes` link names the replacement, and refuses
  moving a superseded decision elsewhere until that link is deleted.
- The status tools' schemas require only `new_status`; pass the single ID or the list, not both.
- Migration 14 rebuilds the `relationships` table so it can store `supersedes` links.

### Structured results (roadmap R10)

The server now lists **23 tools** by default and **24** with `LIFECYCLE_GITHUB=on`, which is the target in ADR-0002. Tool
definitions sent to clients shrink from 12,818 to 11,815 characters. Tools still return text, and most also return the
same facts as data in `structuredContent`. No tool declares an `outputSchema`.

**Breaking:** the removed tools have no aliases. Calling one returns an "Unknown tool" error.

| Removed tool | Use instead |
|---|---|
| `query_requirements_json` | `query_requirements`; `structuredContent` is `{requirements, count}` |
| `query_tasks_json` | `query_tasks`; `structuredContent` is `{tasks, count}` |
| `query_architecture_decisions_json` | `query_architecture_decisions`; `structuredContent` is `{architecture_decisions, count}` |
| `get_project_metrics` | `get_project_status`; `structuredContent` holds the metrics |

Query results include full records. JSON list fields such as `acceptance_criteria` are returned as lists.

#### Changed
- `create_requirement` returns one status line. `structuredContent` holds `id`, `type`, `title`, `priority` and
  `status`.
- `create_task` returns `id`, `status`, `requirement_ids`, `parent_task_id` and `github_issue_url`.
  `create_architecture_decision` returns `id`, `status` and `requirement_ids`.
- `update_requirement`, `update_task` and `update_architecture` return `id`, the `changed` fields and the new
  `revision`. `update_requirement` also returns `changed_since_review`.
- `update_requirement_status`, `update_task_status` and `update_architecture_status` return `id`, `from_status` and
  `to_status`.

### Tool surface streamlined (ADR-0002)

The server now lists **27 tools** by default, down from 39, and **28** with `LIFECYCLE_GITHUB=on`. Tool definitions sent to
clients shrink from 17,136 to 12,818 characters. The evidence and the decision are in
[docs/tool-surface/](docs/tool-surface/).

**Breaking:** removed and renamed tools have no aliases. Clients that call them get an "Unknown tool" error and must
switch to the replacements below.

| Removed tool | Use instead |
|---|---|
| `get_requirement_details(requirement_id)` | `get_details(entity_id)` |
| `get_task_details(task_id)` | `get_details(entity_id)` |
| `get_architecture_details(architecture_id)` | `get_details(entity_id)` |
| `delete_requirement(requirement_id)` | `delete_record(entity_id)` |
| `delete_task(task_id)` | `delete_record(entity_id)` |
| `delete_architecture(architecture_id)` | `delete_record(entity_id)` |
| `add_architecture_review(architecture_id, comment, reviewer)` | `add_comment(entity_id, comment, author)` |
| `get_entity_relationships(entity_id)` | `query_relationships(entity_id)` |
| `query_all_relationships(entity_types)` | `query_relationships(entity_types)`, without `entity_id` |
| `sync_task_from_github(task_id)` | `sync_github_tasks(task_id)`, listed only with `LIFECYCLE_GITHUB=on` |
| `bulk_sync_github_tasks()` | `sync_github_tasks()` without `task_id`, listed only with `LIFECYCLE_GITHUB=on` |
| `start_requirement_interview`, `continue_requirement_interview` | No replacement; call `create_requirement` directly. Roadmap R11 decides whether guided capture returns. |
| `start_architectural_conversation`, `continue_architectural_conversation` | No replacement; call `create_architectural_diagrams` directly |

`entity_id` is any requirement, task or architecture decision ID (`REQ-0001-FUNC-00`, `TASK-0001-00-00`,
`ADR-0001`); the prefix tells the server which kind of record it is.

#### Changed
- `query_relationships` gains `direction` (`incoming`, `outgoing` or `both`) and `entity_types`. Without `entity_id` it
  returns every link as JSON. The `include_incoming` and `include_outgoing` parameters are gone; they had no effect.
- `create_architectural_diagrams` no longer accepts `interactive`.
- `add_comment` works on requirements and tasks as well as architecture decisions. Requirement and task details now
  show a Comments section, including comments given with status changes. The section in architecture details, formerly
  "Reviews", is also called Comments.
- Tool and parameter descriptions are shorter.

#### Added
- `tests/tool_surface_budget.json` records the tool count and definition size per handler, and CI fails when the
  surface grows past it. `scripts/tool_surface_report.py` shows the current sizes.
- `LIFECYCLE_CALL_LOG` makes the server append one JSON line per tool call (tool, argument names, duration, outcome,
  response size); `scripts/tool_usage_report.py` summarises these logs.

### Earlier in this release
- Records can be edited in place with `update_requirement`, `update_task` and `update_architecture`. Every change is
  logged with before and after values and a reason, and `get_entity_history` shows the log. See the README's *Editing,
  Deleting and History* section.
- Create and update tools accept the curated fields, such as `out_of_scope`, `test_plan` and `risk_assessment`.
- Every tool refuses fields it does not declare, naming the field.
- GitHub integration is opt-in with `LIFECYCLE_GITHUB=on`.
