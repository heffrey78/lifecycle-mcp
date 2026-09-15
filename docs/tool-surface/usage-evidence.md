# Tool usage evidence

Roadmap R15 (REQ-0002-NFUNC-00), TASK-0030. This is the input to the tool inventory (TASK-0031) and the tool
surface ADR (TASK-0032). It covers two agent sessions that drove a real project, Quire (a local-first Markdown
notebook in `claude-lifecycle-lab/app`), through lifecycle-mcp.

## Sessions

| | Original lab session | Re-run |
|---|---|---|
| When | 2026-09-14, before R1–R6 | 2026-09-14, branch `roadmap/r15-tool-surface` |
| Tools listed | 32 at the time (39 today) | 39 |
| Log | `claude-lifecycle-lab/lc-calls.jsonl`, records without a `project` field (lab driver; includes argument values, not committed) | [`quire-rerun-2026-09-14-calls.jsonl`](quire-rerun-2026-09-14-calls.jsonl) (server `LIFECYCLE_CALL_LOG`; argument names only) |
| Calls | 162 across 24 tools, 11 error results | 153 across 28 tools, 0 error results |
| Outcome | 8 requirements validated, 13 tasks complete, 5 ADRs; Quire built | Same plan: 8 requirements validated, 13 tasks complete, 5 ADRs (4 accepted, 1 superseded) |

The lab log also holds 160 later calls that loaded this roadmap into the repository's tracker. They planned work
rather than drove a project, so they are left out here.

### How the re-run was done

The same product and plan were run again in a fresh database (`claude-lifecycle-lab/rerun/`) against this
branch's server, in five scripted phases driven over MCP stdio by `lc.py`:

1. Requirements: the 8 original requirements with the fields R6b exposed, a guided interview for the import/export
   requirement, a Draft correction, review and approval.
2. Architecture: the 4 original ADRs, a review that led to an edit while Proposed, the architectural conversation
   and a diagram, acceptance, requirements to Architecture and Ready.
3. Tasks: the original 13 tasks and subtasks, 9 dependencies, one estimate change.
4. Build: tasks worked in dependency order against the existing Quire code. On the way, an approved requirement
   gained an acceptance criterion (with a reason), and ADR-0005 superseded ADR-0004, as happened in the real build.
5. Validation: every requirement to Implemented and Validated with test evidence (172 app tests pass; 10k-note
   search benchmark p95 37.0 ms), history, trace, export, diagram and metrics.

The server log and the driver log agree call for call: same tools in the same order, same error flags, same argument
names.

### Limits of this evidence

- The re-run is a scripted replay by the agent that wrote the edit tools, not an independent agent discovering the
  tools. It shows what a complete lifecycle needs; it says little about how easily a newcomer picks the right tool.
  Its zero error count is not evidence of discoverability.
- Calls the MCP layer rejects before routing (for example an undeclared field) are not in the server log.
- Implementation was not redone: the build phase reports progress against code that already existed.
- GitHub integration was off in both sessions, so the two sync tools could not be used.

## Per tool

Definition size is the tool's `tools/list` entry in compact JSON (`scripts/tool_surface_report.py`). "–" means the
tool did not exist in the original session.

| Tool | Handler | Definition chars | Re-run calls | Original calls |
|---|---|---:|---:|---:|
| `update_requirement_status` | Requirement | 412 | 46 | 52 |
| `update_task_status` | Task | 364 | 26 | 28 |
| `create_task` | Task | 755 | 13 | 14 |
| `create_relationship` | Relationship | 429 | 9 | 13 |
| `create_requirement` | Requirement | 1037 | 8 | 7 |
| `get_project_status` | Status | 193 | 6 | 3 |
| `update_architecture_status` | Architecture | 420 | 6 | 7 |
| `get_requirement_details` | Requirement | 235 | 5 | 2 |
| `create_architecture_decision` | Architecture | 883 | 5 | 5 |
| `continue_requirement_interview` | Interview | 272 | 4 | 8 |
| `continue_architectural_conversation` | Interview | 288 | 3 | 3 |
| `update_requirement` | Requirement | 1427 | 2 | – |
| `update_task` | Task | 1337 | 2 | – |
| `create_architectural_diagrams` | Export | 844 | 2 | 4 |
| `trace_requirement` | Requirement | 226 | 2 | 3 |
| `get_task_details` | Task | 210 | 2 | 2 |
| `update_architecture` | Architecture | 1215 | 1 | – |
| `delete_requirement` | Requirement | 352 | 1 | – |
| `get_entity_history` | Relationship | 351 | 1 | – |
| `start_architectural_conversation` | Interview | 376 | 1 | 1 |
| `export_project_documentation` | Export | 537 | 1 | 1 |
| `add_architecture_review` | Architecture | 304 | 1 | 1 |
| `query_architecture_decisions` | Architecture | 291 | 1 | 1 |
| `query_requirements` | Requirement | 265 | 1 | 0 |
| `start_requirement_interview` | Interview | 253 | 1 | 2 |
| `get_architecture_details` | Architecture | 233 | 1 | 1 |
| `get_entity_relationships` | Relationship | 226 | 1 | 1 |
| `get_project_metrics` | Status | 175 | 1 | 1 |
| `query_all_relationships` | Relationship | 332 | 0 | 1 |
| `query_tasks` | Task | 258 | 0 | 1 |
| `delete_architecture` | Architecture | 371 | 0 | – |
| `delete_task` | Task | 339 | 0 | – |
| `query_relationships` | Relationship | 334 | 0 | 0 |
| `query_architecture_decisions_json` | Architecture | 323 | 0 | 0 |
| `query_requirements_json` | Requirement | 297 | 0 | 0 |
| `delete_relationship` | Relationship | 294 | 0 | 0 |
| `query_tasks_json` | Task | 290 | 0 | 0 |
| `sync_task_from_github` | Task | 222 | 0 | 0 |
| `bulk_sync_github_tasks` | Task | 166 | 0 | 0 |
| **Total** | | **17136** | **153** | **162** |

## What the evidence says

- **Nine tools were never called in either session**, 2,636 definition characters (15% of the surface):
  - the three `*_json` query duplicates (R10 already plans to fold them)
  - the two GitHub sync tools (off in both sessions; candidates for registering only when `LIFECYCLE_GITHUB=on`)
  - `query_relationships`, `delete_relationship`
  - `delete_task`, `delete_architecture`

  The deletes exist for mistakes, so rare use is expected. That alone does not argue for removing them.
- **Status transitions dominate calls**: requirement and task status changes were 72 of 153 calls in the re-run
  (47%) and 80 of 162 in the original (49%). Most came back to back (62 repeats in the re-run, 47 in the original),
  moving several records through the same state. Bulk transitions (R9) would cut the call count, but not the
  definition size.
- **The edit tools earned their place but are the largest definitions**: `update_requirement`, `update_task` and
  `update_architecture` are 3,979 characters (23% of the surface) and were used 5 times, each time for a real plan
  change: a Draft correction, an ADR edit after review, an approved requirement's new criterion, an estimate and a
  renamed task. Most of their size is field lists repeated from the create tools.
- **Interviews produced nothing usable**: the requirement interview (5 calls) ended with a placeholder
  "Requirement from Interview" with every field unspecified, which was deleted and written directly (F-07 is
  unchanged). The architectural conversation (4 calls) ended in a diagram request. The original session's 14
  interview calls went the same way. This supports R11's rethink, and the four interview tools (1,189 characters)
  are candidates for folding or removal there.
- **Reads were few and concentrated**: the re-run made 21 read calls across 10 tools, mostly `get_project_status`
  (6) and `get_requirement_details` (5). Of the three relationship queries, `query_relationships` was never called,
  `query_all_relationships` once and `get_entity_relationships` twice across both sessions.
- **Responses cost context too**: the re-run's responses total 43,201 characters (about 280 per call), 2.5 times
  the whole tool definition set. R10 (quiet, structured responses) is the lever for that side.

### New findings from the re-run

- F-40 [S3] `get_entity_history` clips before and after values at 160 characters, so an edit that appends to a list
  shows two identical-looking prefixes and hides the change.
- F-41 [S3] Architecture details show `Authors` as raw JSON (`["Claude"]`) while `Deciders` is a readable list.
- F-22 (open, R14) is still visible: a requirement's linked tasks and progress count subtasks alongside their parent.

## Reproduce

```bash
# The original Quire session is the lab log's records without a "project" field
python3 -c 'import json,sys; [sys.stdout.write(l) for l in open("claude-lifecycle-lab/lc-calls.jsonl") if l.strip() and "project" not in json.loads(l)]' > /tmp/quire-original.jsonl

# Summaries for one or more logs, compared with the tools this checkout lists
uv run python scripts/tool_usage_report.py docs/tool-surface/quire-rerun-2026-09-14-calls.jsonl /tmp/quire-original.jsonl

# Definition sizes per handler and tool
uv run python scripts/tool_surface_report.py

# Record a new session from any MCP client
LIFECYCLE_CALL_LOG=/path/to/calls.jsonl lifecycle-mcp
```
