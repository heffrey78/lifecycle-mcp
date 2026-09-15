# Changelog

## Unreleased

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
