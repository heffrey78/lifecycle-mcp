# Tool inventory

Roadmap R15 (REQ-0002-NFUNC-00), TASK-0031. Status: **draft for owner review**. The decision itself belongs to
the tool surface ADR (TASK-0032); nothing here removes or renames a tool.

Every tool the server lists today is classified below:

- **keep**: stays as it is, or with a small change noted
- **fold**: goes away, and its capability moves into the named tool and parameter
- **conditional**: listed only when its opt-in feature is enabled
- **remove**: goes away without a replacement tool here; the named roadmap item decides what replaces it

Evidence comes from [usage-evidence.md](usage-evidence.md): calls in the Quire re-run and in the original lab session
("–" where the tool did not exist yet), and each definition's size in `tools/list` (compact JSON characters,
`scripts/tool_surface_report.py`).

## Summary

| | Tools | Definition chars |
|---|---:|---:|
| Today | 39 | 17,136 |
| Target, GitHub off (default) | 23 | 12,685 (74%) |
| Target, GitHub on | 24 | 12,892 |

The target keeps 20 tools, folds 15 into 3 new ID-based tools and one extended query, registers GitHub sync only when
enabled, and removes the 4 interview tools. Sizes for the new and changed tools were measured from candidate
definitions (see [Measuring the target](#measuring-the-target)), not estimated.

No capability is lost except the interviews. Both sessions showed they produce no usable content (F-07, F-15), and
R11 decides their replacement.

## Classification

### Requirements

| Tool | Chars | Calls (re-run / original) | Class | Where the capability goes | Roadmap |
|---|---:|---|---|---|---|
| `create_requirement` | 1037 | 8 / 7 | keep | | |
| `update_requirement` | 1427 | 2 / – | keep | | trim parameter descriptions |
| `update_requirement_status` | 412 | 46 / 52 | keep | | R9 bulk transitions |
| `query_requirements` | 265 | 1 / 0 | keep | returns structured results too | R10 |
| `query_requirements_json` | 297 | 0 / 0 | fold | `query_requirements` structured result | R10 |
| `get_requirement_details` | 235 | 5 / 2 | fold | `get_details(entity_id)` | R16 |
| `trace_requirement` | 226 | 2 / 3 | keep | | |
| `delete_requirement` | 352 | 1 / – | fold | `delete_record(entity_id)` | R16 |

### Tasks

| Tool | Chars | Calls (re-run / original) | Class | Where the capability goes | Roadmap |
|---|---:|---|---|---|---|
| `create_task` | 755 | 13 / 14 | keep | | |
| `update_task` | 1337 | 2 / – | keep | | trim parameter descriptions |
| `update_task_status` | 364 | 26 / 28 | keep | | R9 bulk transitions |
| `query_tasks` | 258 | 0 / 1 | keep | returns structured results too | R10 |
| `query_tasks_json` | 290 | 0 / 0 | fold | `query_tasks` structured result | R10 |
| `get_task_details` | 210 | 2 / 2 | fold | `get_details(entity_id)` | R16 |
| `delete_task` | 339 | 0 / – | fold | `delete_record(entity_id)` | R16 |
| `sync_task_from_github` | 222 | 0 / 0 | conditional, fold | `sync_github_tasks(task_id)` | R16 |
| `bulk_sync_github_tasks` | 166 | 0 / 0 | conditional, fold | `sync_github_tasks` without `task_id` | R16 |

### Architecture decisions

| Tool | Chars | Calls (re-run / original) | Class | Where the capability goes | Roadmap |
|---|---:|---|---|---|---|
| `create_architecture_decision` | 883 | 5 / 5 | keep | | |
| `update_architecture` | 1215 | 1 / – | keep | | trim parameter descriptions |
| `update_architecture_status` | 420 | 6 / 7 | keep | | R9 (superseding sets `superseded_by`) |
| `query_architecture_decisions` | 291 | 1 / 1 | keep | returns structured results too | R10 |
| `query_architecture_decisions_json` | 323 | 0 / 0 | fold | `query_architecture_decisions` structured result | R10 |
| `get_architecture_details` | 233 | 1 / 1 | fold | `get_details(entity_id)` | R16 |
| `add_architecture_review` | 304 | 1 / 1 | fold | `add_comment(entity_id, comment, author)`, which also lets requirements and tasks be commented on (F-39) | R16 |
| `delete_architecture` | 371 | 0 / – | fold | `delete_record(entity_id)` | R16 |

### Relationships and history

| Tool | Chars | Calls (re-run / original) | Class | Where the capability goes | Roadmap |
|---|---:|---|---|---|---|
| `create_relationship` | 429 | 9 / 13 | keep | | |
| `delete_relationship` | 294 | 0 / 0 | keep | the only way to undo a link | |
| `query_relationships` | 334 | 0 / 0 | keep, extended | `entity_id` becomes optional, plus `direction` and `entity_types`, to absorb the two tools below | R16 |
| `get_entity_relationships` | 226 | 1 / 1 | fold | `query_relationships(entity_id)` | R16 |
| `query_all_relationships` | 332 | 0 / 1 | fold | `query_relationships(entity_types)` without `entity_id` | R16 |
| `get_entity_history` | 351 | 1 / – | keep | | |

### Interviews

| Tool | Chars | Calls (re-run / original) | Class | Where the capability goes | Roadmap |
|---|---:|---|---|---|---|
| `start_requirement_interview` | 253 | 1 / 2 | remove | replacement decided by R11 (schema-driven interview or a requirement template) | R11 |
| `continue_requirement_interview` | 272 | 4 / 8 | remove | as above | R11 |
| `start_architectural_conversation` | 376 | 1 / 1 | remove | diagrams are requested directly with `create_architectural_diagrams` | R11, R13 |
| `continue_architectural_conversation` | 288 | 3 / 3 | remove | as above | R11, R13 |

### Status and export

| Tool | Chars | Calls (re-run / original) | Class | Where the capability goes | Roadmap |
|---|---:|---|---|---|---|
| `get_project_status` | 193 | 6 / 3 | keep | returns structured results too | R10 |
| `get_project_metrics` | 175 | 1 / 1 | fold | `get_project_status` structured result | R10 |
| `export_project_documentation` | 537 | 1 / 1 | keep | | |
| `create_architectural_diagrams` | 844 | 2 / 4 | keep | drop `interactive`, which only starts the conversation tools (727 chars without it) | R13 |

## Proposed principles for the ADR

Drawn from the classification, for TASK-0032 to accept, change or reject:

1. **Per record type only where inputs differ.** Create, update, status and query keep one tool per record type
   because their parameters differ. Operations whose only input is a record ID (details, delete, history, comment)
   are one tool across types; the ID prefix already names the type.
2. **One tool per operation, not per output format.** Structured results (R10) replace `*_json` twins. Return
   `structuredContent` without declaring an `outputSchema` unless the budget allows it; output schemas count
   against it too.
3. **Opt-in features register only when enabled.** GitHub sync is listed only with `LIFECYCLE_GITHUB=on`.
4. **No multi-step conversation tools without persisted state.** Interviews are replaced under R11, not kept as they
   are.
5. **The budget moves with the change.** Growth raises `tests/tool_surface_budget.json` in the same change, and each
   fold lowers it to the new measured size.

## Open questions for the owner

1. **Status tools.** They get about half of all calls. Folding the three into one `update_status(entity_id,
   new_status, comment)` would save two more tools, but the agent would lose each type's valid statuses in the
   schema. The target keeps them; R9's bulk transitions touch the same tools, so decide both together.
2. **Renames.** `get_details`, `delete_record` and `add_comment` replace per-type names. Existing clients break once;
   R16 lists every removal and its replacement in a changelog. Keep the old names as aliases for one release, or not?
3. **Interviews.** Remove them now (R16), or keep them until R11 ships a replacement?
4. **Descriptions.** Description text is 21% of the definition size today (3,578 chars). The three update tools'
   parameter descriptions alone are 641 chars, mostly the repeated `reason`, `actor` and `if_revision` explanations.
   Trim them as part of R16?
5. **Responses.** Responses in the re-run totalled 43,201 characters, 2.5 times the definitions. Should R10 set a
   response budget as well?

## One change per tool

| Roadmap item | Tools it changes |
|---|---|
| R10 quiet, structured responses | fold the three `*_json` tools and `get_project_metrics`; structured results for the three query tools and `get_project_status` |
| R11 interviews | remove the four interview tools; decide their replacement |
| R13 diagrams | `create_architectural_diagrams` (drop `interactive` once the conversation tools are gone) |
| R9 traceability and bulk transitions | the three status tools (bulk form, `superseded_by`); decide open question 1 at the same time |
| R16 streamline | `get_details`, `delete_record`, `add_comment`, the extended `query_relationships`, `sync_github_tasks` and conditional registration; parameter description trimming; lower the budget |

## Measuring the target

Measured on 2026-09-14 with the server from this branch:

- the 18 kept tools that do not change: 10,694 chars
- `create_architectural_diagrams` without `interactive`: 727
- candidate `get_details(entity_id)`: 246
- candidate `delete_record(entity_id)`: 341
- candidate `add_comment(entity_id, comment, author)`: 303
- candidate `query_relationships(entity_id, relationship_type, direction, entity_types)`: 374
- candidate `sync_github_tasks(task_id)`: 207

Candidates were built as `mcp.types.Tool` objects with the same `additionalProperties: false` the server adds, and
measured the way the budget test measures. Their descriptions were written for this measurement and will change in
implementation; the budget test measures the real result.
