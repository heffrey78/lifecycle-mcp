# Lifecycle MCP Server

A Model Context Protocol (MCP) server for comprehensive software lifecycle management. This server provides structured tracking of requirements, tasks, and architecture decisions through a SQLite database with full traceability and automated state management.

## Features

- **Requirements Management**: Create and manage software requirements with validation and lifecycle tracking
- **Task Management**: Track implementation tasks with hierarchical structure and effort estimation
- **Architecture Decisions**: Record ADRs (Architecture Decision Records) with full context
- **Project Dashboards**: Real-time project health metrics and status reporting
- **Requirement Tracing**: Complete traceability from requirements through implementation
- **State Validation**: Automatic validation of lifecycle state transitions
- **Safe Editing and History**: Edit records in place with per-field history, reasons for approved requirements and revision checks; delete records created by mistake
- **Relationship Tracking**: Many-to-many relationships between requirements, tasks, and architecture

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/heffrey78/lifecycle-mcp.git
cd lifecycle-mcp

# 2. Install globally (easiest for using across projects)
uv tool install .        # or: pip install -e .

# 3. Go to any project where you want to use lifecycle management
cd /path/to/your/project

# 4. Add the MCP server to Claude
claude mcp add lifecycle lifecycle-mcp -e LIFECYCLE_DB=/path/to/your/project/lifecycle.db

# 5. Start using lifecycle tools in Claude!
```

## Installation Options

### Prerequisites (Optional)
If you want to use `uv` (faster Python package manager):
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with homebrew
brew install uv
```

### Clone the Repository
```bash
git clone https://github.com/heffrey78/lifecycle-mcp.git
cd lifecycle-mcp
```

## Usage with Claude Code

For detailed examples and scenarios, see [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md).

### Option 1: Global Installation (Recommended for Multiple Projects)

Install the server globally so it can be used from any project:

```bash
# From the lifecycle-mcp directory (add --editable to pick up source changes)
uv tool install .        # or: pip install -e .

# Now from ANY project directory, add the server:
claude mcp add lifecycle lifecycle-mcp -e LIFECYCLE_DB=./lifecycle.db
```

**Note**: Each project gets its own database file in its directory.

### Option 2: Run from Source with uv

If you prefer not to install globally:

```bash
# Get the full path to the lifecycle-mcp directory
LIFECYCLE_PATH="/path/to/lifecycle-mcp"  # Replace with your actual path

# From any project directory:
claude mcp add lifecycle $(which uv) -- --directory $LIFECYCLE_PATH run server.py -e LIFECYCLE_DB=./lifecycle.db
```

### Option 3: Direct Python Execution

For maximum compatibility:

```bash
# Get the full path to the server
LIFECYCLE_PATH="/path/to/lifecycle-mcp"  # Replace with your actual path

# From any project directory:
claude mcp add lifecycle $(which python) $LIFECYCLE_PATH/server.py -e LIFECYCLE_DB=./lifecycle.db
```

## Manual Configuration

You can also manually edit your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "lifecycle": {
      "command": "lifecycle-mcp",
      "env": {
        "LIFECYCLE_DB": "./lifecycle.db"
      }
    }
  }
}
```

## Best Practices

### Database Location
- Each project should have its own `lifecycle.db` file
- Use `LIFECYCLE_DB=./lifecycle.db` to create the database in the current project
- Or use an absolute path for a shared database: `LIFECYCLE_DB=/path/to/shared/lifecycle.db`

### Virtual Environment (Recommended)
```bash
# Create a virtual environment for lifecycle-mcp
cd /path/to/lifecycle-mcp
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in the virtual environment
pip install -e .

# Find the venv's lifecycle-mcp command
which lifecycle-mcp  # Copy this path

# Use the full path when adding to Claude
claude mcp add lifecycle /path/to/venv/bin/lifecycle-mcp -e LIFECYCLE_DB=./lifecycle.db
```

## MCP Tools Reference

The server exposes 23 MCP tools (24 with GitHub integration on) across 7 handler modules for comprehensive lifecycle management. Every tool rejects fields it does not declare, and the error names the field. [CHANGELOG.md](CHANGELOG.md) lists tools that were removed or renamed, with their replacements.

Results are text for the model to read. Most tools also return the same facts as data in `structuredContent`: create tools return the new ID and status, edit tools the changed fields and new revision, status tools the old and new status (a list of IDs gets a result per ID), and query tools the full records. No tool declares an `outputSchema`.

### Tool List
**Requirements**
- `create_requirement` - Create new requirements
- `update_requirement` - Edit a requirement's content (a reason is required at Approved or later)
- `update_requirement_status` - Move one or many requirements through lifecycle states, stepping through the allowed path
- `query_requirements` - Search and filter requirements, including the ones whose work is done and only the decision is missing; the matching records also come back as structured data
- `trace_requirement` - Trace requirement through implementation

**Tasks**
- `create_task` - Create implementation tasks from requirements
- `update_task` - Edit a task's content, move it to another parent or change its requirements
- `update_task_status` - Update the progress of one or many tasks; the comment on a move to Blocked is kept as the reason
- `query_tasks` - Search and filter tasks, including the ones ready to start; the matching records also come back as structured data
- `sync_github_tasks` - Sync one task, or every linked task, from GitHub issues (listed only when `LIFECYCLE_GITHUB=on`)

**Architecture decisions**
- `create_architecture_decision` - Record architecture decisions (ADRs)
- `update_architecture` - Edit a Proposed architecture decision
- `update_architecture_status` - Update the status of one or many architecture decisions; Superseded comes from a supersedes link
- `query_architecture_decisions` - Search and filter architecture decisions; the matching records also come back as structured data

**Any record (requirement, task or architecture decision, by ID)**
- `get_details` - Full details of a record, with its links and comments
- `delete_record` - Delete a Draft requirement, Not Started task or Proposed architecture decision created by mistake
- `add_comment` - Comment on a record; comments show in its details and history

**Relationships and history**
- `create_relationship` - Link two records: dependencies, refinements, blocks, a task implementing an architecture decision, a newer decision superseding an older one, and more
- `delete_relationship` - Remove a link between two records
- `query_relationships` - Query links: one record's links by direction and type, or every link as JSON for a graph
- `get_entity_history` - Show how a record changed: creation, edits with before and after values, status changes, comments and deletion

**Status and export**
- `get_project_status` - Project health dashboard; the metrics also come back as structured data
- `export_project_documentation` - Export comprehensive markdown documentation
- `create_architectural_diagrams` - Generate Mermaid diagrams for project visualization

### Editing, Deleting and History

These rules apply to `update_requirement`, `update_task`, `update_architecture` and `delete_record`:

- **Edits happen in place.** Update tools change content only; status moves stay with the `update_*_status` tools, and record IDs never change.
- **Every change is recorded.** Each changed field is logged with its before and after values, the actor and the reason. `get_entity_history` shows the log.
- **Revisions guard against lost updates.** Each record has a revision, shown in its details, that goes up by one with every update that changes something. Pass `if_revision` to have the update refused, with nothing written, when the record has changed since you read it.
- **Approved requirements need a reason.** Editing a requirement at Approved or later requires `reason`. The requirement then shows as *Changed Since Last Review* in `get_details`, `trace_requirement` and `get_project_status`, listing the edited fields.
- **The next status change is the acknowledgement.** There is no separate acknowledgement step: the requirement's next status transition clears the flag, and that transition's comment records the review.
- **Decided architecture is not rewritten.** Architecture decisions can be edited only while Proposed. To change a decided one, record a new decision with `create_architecture_decision` and link it with `create_relationship` (`supersedes`, newer to older), which moves the old one to Superseded.
- **Deleting is for mistakes.** Only Draft requirements, Not Started tasks and Proposed architecture decisions can be deleted, and only when nothing depends on them. Refusals name the blocking records. A deleted record's own links go with it, and its history remains.

#### `get_entity_history`
Show how a requirement, task or architecture decision changed over time, oldest first.

**Parameters:**
- `entity_id` (required): Requirement, task or architecture decision ID

**Returns:** Creation, field edits with before and after values and reasons, status changes, comments and deletion. Still available after the record is deleted.

#### `get_details`
Full details of a requirement, task or architecture decision. The ID prefix (`REQ-`, `TASK-`, `ADR-`) tells the server which kind of record it is.

**Parameters:**
- `entity_id` (required): Requirement, task or architecture decision ID

**Returns:** The record's fields, revision, links (linked tasks, subtasks and parent, linked requirements, the tasks implementing a decision, the decisions a task implements, the decisions a decision supersedes or is superseded by, and the tasks a task depends on or blocks) and comments. A Blocked task shows its blocked reason. A reviewed requirement edited since its last status change is flagged *Changed Since Last Review*.

#### `delete_record`
Delete a record created by mistake.

**Parameters:**
- `entity_id` (required): Requirement, task or architecture decision ID

Only Draft requirements, Not Started tasks and Proposed architecture decisions can be deleted. Refused, naming what blocks it, when:
- **Requirement:** tasks, architecture decisions or other requirements link to it.
- **Task:** it has subtasks, other tasks depend on it, or it is linked to a GitHub issue.
- **Architecture decision:** another decision is superseded by it, or records other than its own requirement links point to it.

Anything past its early stage changes status instead (Deprecated, Abandoned, Rejected or Superseded).

#### `add_comment`
Comment on a requirement, task or architecture decision.

**Parameters:**
- `entity_id` (required): Requirement, task or architecture decision ID
- `comment` (required): The comment
- `author` (optional): Who wrote it (default: MCP User)

**Returns:** Confirmation. The comment appears in the record's details under Comments and in `get_entity_history`.

### Requirement Management

#### `create_requirement`
Create a new requirement.

**Parameters:**
- `type` (required): Requirement type - "FUNC", "NFUNC", "TECH", "BUS", "INTF"
- `title` (required): Descriptive title
- `priority` (required): Priority level - "P0", "P1", "P2", "P3"
- `current_state` (required): Current system state
- `desired_state` (required): Target system state
- `functional_requirements` (optional): Array of functional requirements
- `acceptance_criteria` (optional): Array of acceptance criteria
- `business_value` (optional): Business justification
- `risk_level` (optional): Risk assessment - "High", "Medium", "Low"
- `author` (optional): Requirement author
- `nonfunctional_requirements` (optional): Array of non-functional requirements (performance, security, ...)
- `technical_constraints` (optional): Array of technical constraints
- `business_rules` (optional): Array of business rules
- `validation_metrics` (optional): Array of metrics that show the requirement is met
- `out_of_scope` (optional): Array of things explicitly not covered

**Example:**
```json
{
  "type": "FUNC",
  "title": "User Authentication System",
  "priority": "P1",
  "current_state": "No user authentication exists",
  "desired_state": "Secure user login with JWT tokens",
  "functional_requirements": ["Login with email/password", "JWT token generation"],
  "acceptance_criteria": ["User can login successfully", "Token expires after 24 hours"],
  "business_value": "Enables secure user access to protected features",
  "risk_level": "Medium"
}
```

#### `update_requirement_status`
Move one or many requirements through their lifecycle with validation.

**Parameters:**
- `requirement_id`: Requirement ID (e.g., "REQ-0001-FUNC-00")
- `requirement_ids`: Instead of `requirement_id`, a list of requirement IDs to move to the same status
- `new_status` (required): Target status - "Draft", "Under Review", "Approved", "Architecture", "Ready", "Implemented", "Validated", "Deprecated"
- `comment` (optional): Review comment or justification, added once to each requirement moved

Pass `requirement_id` or `requirement_ids`, not both. Each ID in a list moves on its own: the result lists every ID, and `structuredContent` holds `results` (one entry per ID, with `error` when refused), `moved` and `refused`. Some refusals make it a warning while the other IDs still move; it is an error only when none moved.

When `new_status` is more than one step away, the requirement walks the shortest allowed path and each step is logged as its own status change: Draft → Approved goes through Under Review, and Approved → Validated through Ready and Implemented. A move never passes through Approved or Validated; those can only be where it ends. Gates apply before anything changes, so a refused move leaves the requirement where it was. Multi-step results include the `path`.

**Valid State Transitions:**
- Draft → Under Review, Deprecated
- Under Review → Draft, Approved, Deprecated
- Approved → Architecture, Ready, Deprecated
- Architecture → Ready, Approved
- Ready → Implemented, Deprecated
- Implemented → Validated, Ready
- Validated → Deprecated

#### `query_requirements`
Search and filter requirements by various criteria.

**Parameters:**
- `status` (optional): Filter by status
- `priority` (optional): Filter by priority level
- `type` (optional): Filter by requirement type
- `search_text` (optional): Text search in title and desired state
- `work_complete` (optional): `true` for the requirements whose linked tasks are all Complete but that have not reached Implemented - the work is done and only the decision is missing

#### `trace_requirement`
Trace a requirement through its complete implementation lifecycle.

**Parameters:**
- `requirement_id` (required): Requirement ID

**Returns:** Complete trace including requirement details, implementation tasks, and architecture decisions.

#### `update_requirement`
Edit a requirement's content in place. See [Editing, Deleting and History](#editing-deleting-and-history) for the rules.

**Parameters:**
- `requirement_id` (required): Requirement ID
- `title`, `priority`, `risk_level`, `current_state`, `desired_state`, `functional_requirements`, `acceptance_criteria`, `business_value`, `nonfunctional_requirements`, `technical_constraints`, `business_rules`, `validation_metrics`, `out_of_scope` (at least one): New values, with the same types as in `create_requirement`
- `reason` (required at Approved or later): Why the change is made
- `actor` (optional): Who makes the change (default: MCP User)
- `if_revision` (optional): Refuse the edit unless the requirement is still at this revision

**Example:**
```json
{
  "requirement_id": "REQ-0001-FUNC-00",
  "acceptance_criteria": ["User can login successfully", "Token expires after 1 hour"],
  "reason": "Security review shortened token lifetime",
  "if_revision": 2
}
```

### Task Management

#### `create_task`
Create implementation tasks linked to requirements.

**Parameters:**
- `requirement_ids` (required): Array of requirement IDs to link
- `title` (required): Task title
- `priority` (required): Priority level - "P0", "P1", "P2", "P3"
- `effort` (optional): Effort estimation - "XS", "S", "M", "L", "XL"
- `user_story` (optional): User story description
- `acceptance_criteria` (optional): Array of acceptance criteria
- `parent_task_id` (optional): Parent task for subtasks
- `assignee` (optional): Task assignee
- `implementation_plan` (optional): Array of implementation steps
- `test_plan` (optional): Array of tests or checks to run
- `definition_of_done` (optional): Array of conditions for calling the task done

**Example:**
```json
{
  "requirement_ids": ["REQ-0001-FUNC-00"],
  "title": "Implement JWT token generation",
  "priority": "P1",
  "effort": "M",
  "user_story": "As a developer, I need JWT token generation so users can authenticate securely",
  "acceptance_criteria": ["Generate JWT with user claims", "Token expires in 24 hours"],
  "assignee": "john.doe@company.com"
}
```

#### `update_task_status`
Update task progress and assignment.

**Parameters:**
- `task_id`: Task ID (e.g., "TASK-0001-00-00")
- `task_ids`: Instead of `task_id`, a list of task IDs to move to the same status, with a result per ID as in `update_requirement_status`
- `new_status` (required): New status - "Not Started", "In Progress", "Blocked", "Complete", "Abandoned"
- `comment` (optional): Status update comment. On a move to Blocked it is kept as the task's blocked reason until the task leaves Blocked; moving a Blocked task to Blocked again without a comment keeps the reason
- `assignee` (optional): New assignee
- `commit` (optional): The commit behind this move, kept on the task
- `evidence` (optional): The test result or check behind this move, kept on the task

`commit` and `evidence` stay on the task after the move: a later status change that omits them leaves them in place, and passing new values replaces them. Both appear in the task's details and in the exported task documentation, so the reasoning behind a completed task survives the hand-off.

#### `query_tasks`
Search and filter tasks by various criteria.

**Parameters:**
- `status` (optional): Filter by status
- `priority` (optional): Filter by priority level
- `assignee` (optional): Filter by assignee
- `requirement_id` (optional): Filter by linked requirement
- `ready` (optional): `true` for Not Started tasks whose dependencies are all Complete, highest priority first. A task waits on the tasks it depends on or requires, and on the tasks that block it

Filters combine.

When `ready` finds nothing, the answer says which case it is rather than that no tasks were found: no tasks remain, every remaining task is waiting (with how many are Blocked and how many wait on dependencies), or the only startable work is already In Progress.

#### `sync_github_tasks`
Sync tasks from their linked GitHub issues, with conflict detection. Listed only when `LIFECYCLE_GITHUB=on`.

**Parameters:**
- `task_id` (optional): Task to sync with its linked GitHub issue; omit it to sync every task linked to an issue

**Returns:** Sync status and any updates applied from the GitHub issue data.

#### `update_task`
Edit a task's content, move it under another parent or change the requirements it implements. The task ID never changes.

**Parameters:**
- `task_id` (required): Task ID
- `title`, `priority`, `effort`, `user_story`, `acceptance_criteria`, `assignee`, `implementation_plan`, `test_plan`, `definition_of_done` (optional): New values, with the same types as in `create_task`
- `parent_task_id` (optional): New parent task; an empty string makes it a top-level task. A task cannot become its own parent or move under one of its subtasks
- `requirement_ids` (optional): Replaces the requirements the task implements; requirements being added must be approved, as in `create_task`
- `reason`, `actor`, `if_revision` (optional): As in `update_requirement`

Pass at least one field to change. Changes are not pushed to a linked GitHub issue.

### Architecture Management

#### `create_architecture_decision`
Record architecture decisions (ADRs) with full context.

**Parameters:**
- `requirement_ids` (required): Array of requirement IDs addressed
- `title` (required): Decision title
- `context` (required): Decision context and background
- `decision` (required): The decision made
- `consequences` (optional): Decision consequences object
- `decision_drivers` (optional): Array of factors driving the decision
- `considered_options` (optional): Array of alternatives considered
- `authors` (optional): Array of decision authors
- `deciders` (optional): Array of people who made the decision
- `implementation_notes` (optional): Notes for implementing the decision
- `validation_criteria` (optional): Array of checks that show the decision works
- `risk_assessment` (optional): Array of risks, each with likelihood, impact and mitigation

**Example:**
```json
{
  "requirement_ids": ["REQ-0001-FUNC-00"],
  "title": "Use JWT for authentication tokens",
  "context": "Need secure, stateless authentication for API access",
  "decision": "Implement JWT tokens with RS256 signing",
  "consequences": {
    "positive": ["Stateless authentication", "Industry standard"],
    "negative": ["Token size overhead", "Key management complexity"]
  },
  "decision_drivers": ["Security requirements", "Scalability needs"],
  "considered_options": ["Session cookies", "OAuth2", "JWT tokens"]
}
```

#### `update_architecture_status`
Update the status of one or many architecture decisions.

**Parameters:**
- `architecture_id`: Architecture ID (e.g., "ADR-0001")
- `architecture_ids`: Instead of `architecture_id`, a list of decision IDs to move to the same status, with a result per ID as in `update_requirement_status`
- `new_status` (required): New status - "Proposed", "Accepted", "Rejected", "Deprecated", "Superseded", "Draft", "Under Review", "Approved", "Implemented"
- `comment` (optional): Status change comment

Superseded comes from a link: `create_relationship` with the newer decision as `source_id`, the older one as `target_id` and `relationship_type` `supersedes` moves the older one to Superseded and sets its `superseded_by`. This tool refuses Superseded without that link, and refuses moving a superseded decision elsewhere until the link is deleted.

#### `query_architecture_decisions`
Search and filter architecture decisions by various criteria.

**Parameters:**
- `status` (optional): Filter by status
- `type` (optional): Filter by type (ADR, TDD, INTG)
- `requirement_id` (optional): Filter by linked requirement
- `search_text` (optional): Text search in title and context

#### `update_architecture`
Edit an architecture decision's content while it is Proposed. Decisions in any other status are refused: record a new decision with `create_architecture_decision` and link it to the old one with a `supersedes` relationship, which moves the old one to Superseded.

**Parameters:**
- `architecture_id` (required): Architecture ID
- `title`, `context`, `decision`, `consequences`, `decision_drivers`, `considered_options`, `authors`, `deciders`, `implementation_notes`, `validation_criteria`, `risk_assessment` (at least one): New values, with the same types as in `create_architecture_decision`
- `reason`, `actor`, `if_revision` (optional): As in `update_requirement`

### Project Monitoring

#### `get_project_status`
Get comprehensive project health metrics and dashboards.

**Parameters:**
- `include_blocked` (optional): Include blocked items analysis (default: true)

**Returns:** Dashboard with requirement overview, task statistics, completion percentages, and blocked items: every Blocked task with its reason, and every task or requirement still waiting on a dependency with what it waits on. `structuredContent` holds the metrics and, when `include_blocked` is on, the same items under `blocked`.

### Documentation Export Tools

#### `export_project_documentation`
Export comprehensive project documentation in structured markdown format.

**Parameters:**
- `project_name` (optional): Name for the project used in filenames (default: "project")
- `include_requirements` (optional): Include requirements documentation (default: true)
- `include_tasks` (optional): Include tasks documentation (default: true)
- `include_architecture` (optional): Include architecture documentation (default: true)
- `output_directory` (optional): Directory to save exported files (default: ".")

**Returns:** List of exported files with their paths.

**Generated Files:**
- `{project_name}-requirements.md` - Complete requirements documentation grouped by type
- `{project_name}-tasks.md` - Task documentation grouped by status, with linked requirements, each task's commit and evidence, and its comments
- `{project_name}-architecture.md` - Architecture decisions with context, decisions, and consequences

**Example:**
```json
{
  "project_name": "ecommerce-platform",
  "include_requirements": true,
  "include_tasks": true,
  "include_architecture": true,
  "output_directory": "./docs"
}
```

#### `create_architectural_diagrams`
Generate Mermaid diagrams for project architecture and relationships visualization.

**Parameters:**
- `diagram_type` (optional): Type of diagram - "requirements", "tasks", "architecture", "full_project", "dependencies" (default: "full_project")
- `limit` (optional): Cap each kind of record. The response says what was drawn and what the limit left out; without it nothing is capped
- `requirement_ids` (optional): Array of specific requirement IDs to include
- `include_relationships` (optional): Include relationship arrows in diagrams (default: true)
- `output_format` (optional): Output format - "mermaid", "markdown_with_mermaid" (default: "mermaid")

**Returns:** Mermaid diagram code or markdown-wrapped diagram.

**Diagram Types:**
- **requirements**: Requirements grouped by type, with parent and depends edges, in status colours
- **tasks**: Tasks with subtask, dependency and blocks edges, in status colours
- **architecture**: Decisions, what they supersede, and the requirements each one addresses
- **full_project**: The whole graph - requirements, tasks and decisions with every link between them
- **dependencies**: The tasks that wait on other tasks, named rather than bare IDs

Every edge reads source to target with a label, so a dependency points at what it waits on. Deprecated requirements and decisions are left out, and the response says how many were. Each type writes one file, `{diagram_type}-diagram.mmd` or `.md`, overwritten on each render.

**Status Colors:**
- Requirements: Draft (red), Under Review (orange), Approved (blue), Ready (green), etc.
- Tasks: Not Started (red), In Progress (orange), Blocked (dark red), Complete (green), etc.
- Architecture: Proposed (orange), Accepted (green), Rejected (red), Deprecated (gray), etc.

**Example:**
```json
{
  "diagram_type": "requirements",
  "include_relationships": true,
  "output_format": "markdown_with_mermaid"
}
```

## Database Schema

The server maintains a comprehensive SQLite database with the following key entities:

- **Requirements**: Central entity with lifecycle states (Draft → Under Review → Approved → Architecture → Ready → Implemented → Validated → Deprecated)
- **Tasks**: Implementation work items with hierarchical structure (TASK-XXXX-YY-ZZ format)
- **Architecture**: ADRs and technical design documents
- **Relationships**: Many-to-many links between requirements, tasks, and architecture
- **Events**: Automatic logging of lifecycle events and status changes
- **Comments**: Notes on requirements, tasks and architecture decisions, added with `add_comment` or a status change's `comment`

### Short IDs

Anywhere a tool takes a record ID, the zero padding and the trailing version can be left out:

| Typed | Resolves to |
|---|---|
| `REQ-12-FUNC` | `REQ-0012-FUNC-00` |
| `TASK-12` | `TASK-0012-00-00` |
| `TASK-12-1` | `TASK-0012-01-00` |
| `ADR-4` | `ADR-0004` |

A requirement's short form keeps its type, because requirement numbers repeat across types: `REQ-12` on its own can mean four different records. Full stored IDs always work. An alias that matches nothing is refused as unknown, and one that matches several is refused naming the candidates, so a tool never acts on a guess. Stored IDs never change; this is only an input form.

### Refused Calls

A call whose arguments do not match the tool's schema is refused before anything is written, naming the field at fault. When the refused parameter has a near neighbour in the same schema that would have taken the value, the message names it: passing a list to `requirement_id` answers that `requirement_ids` takes an array and accepts what you passed. The suggestion is read from the tool's own schema, so a new singular/plural pair is covered the day it is declared.

Refused calls reach the call log like any other when `LIFECYCLE_CALL_LOG` is set, so a session's totals cover the calls a client got wrong rather than only the ones that reached a handler.

## Entity ID Formats

- **Requirements**: `REQ-XXXX-TYPE-VV` (e.g., REQ-0001-FUNC-00)
- **Tasks**: `TASK-XXXX-YY-ZZ` (e.g., TASK-0001-00-00)
- **Architecture**: `ADR-XXXX` (e.g., ADR-0001)

## Environment Variables

- `LIFECYCLE_DB`: Path to SQLite database file (default: "./lifecycle.db")
- `LIFECYCLE_GITHUB`: Set to `on` to create and sync a GitHub issue for each task (default: off). Requires an authenticated `gh` CLI and a github.com `origin` remote in the server's working directory. When off, the server never runs `gh` or `git`, and the `sync_github_tasks` tool is not listed.
- `LIFECYCLE_RULES`: How strictly risky status moves are treated - `off`, `warn` or `enforce` (default: `warn`). Anything else falls back to `warn`.
- `LIFECYCLE_STALE_AFTER`: How many days a requirement may go unchecked before `get_project_status` chases it (default: 14). `0` chases every requirement as soon as it is written. Anything that is not a number of days falls back to the default.
- `LIFECYCLE_CALL_LOG`: Path to a file where the server appends one JSON line per tool call: tool name, argument names (not values), duration, whether it failed and response size. Off by default. Every call the server receives is logged, including one its schema refused and one naming a tool that does not exist: those carry `error_kind` (`validation`, `unknown_tool`) and the rule and parameter they were refused by, so a session's totals cover the calls a client got wrong. `scripts/tool_usage_report.py` summarises these logs.

### Writing Requirements

The server offers an MCP prompt, `capture_requirement`, listed under `prompts/list`. It is a guide for writing a well-formed requirement that your own model fills in and then passes to `create_requirement` in a single call; it takes an optional `about` argument carrying what the person said in their own words. Nothing is kept on the server between calls.

New records also say when they are thin for their kind: a requirement with no `acceptance_criteria`, an NFUNC requirement with no `validation_metrics`, a P0 or P1 task with no `test_plan`. These are workflow rules, so they warn by default, refuse under `LIFECYCLE_RULES=enforce`, and are silent under `off`.

A requirement's details show when anyone last checked it against reality, and `get_project_status` lists the ones worth re-reading under Needs Verification: those whose content changed after the last check, and those nobody has checked for longer than `LIFECYCLE_STALE_AFTER` days. Writing a requirement counts as the first check, and after that commenting on it or moving its status does, so nothing is chased on the day it was written. The line states the two times it holds - when the content changed, and when it was last checked - and never claims to know the moment the requirement went stale.

When every task implementing a requirement is Complete but the requirement has not reached Implemented, the work is done and only the decision is missing. `get_project_status` names those requirements under Work Complete, Decision Pending, and `query_requirements` finds them with `work_complete`. Nothing moves on its own: the tracker prompts and the person decides.

### Workflow Rules

A status move can be risky without being wrong. `LIFECYCLE_RULES` decides what happens then:

- **`warn` (default):** the move happens exactly as it does today, and the response says why it was risky, in the text and in `structuredContent` under `warnings` - per record for a list of IDs.
- **`enforce`:** the move is refused before anything is written, naming what blocks it.
- **`off`:** nothing is checked.

The rules:

- **Unfinished dependencies:** starting or completing a task whose dependencies are not all Complete names them. An abandoned dependency is named separately, with the two ways out: drop the link with `delete_relationship`, or abandon the waiting task too.
- **Open subtasks:** completing a task while a subtask is neither Complete nor Abandoned names the open subtasks.
- **Skips and reopens:** completing a task that was never started or is still Blocked, and reopening a Complete task, each say so.
- **The Implemented gate:** a requirement reaching Implemented while the tasks implementing it are open names them.
- **Decision moves:** an architecture decision moving outside its vocabulary says where that status usually goes. The ADR statuses and the TDD chain are separate sets.

Three rules are always on, whatever the mode, because they protect what the server maintains itself: a requirement cannot be Validated while a linked task is open, Superseded needs a `supersedes` link, and a requirement's status still follows its transition map.

## Troubleshooting

### Connection Issues

**"MCP error -32000: Connection closed"**

The server exited or wrote something other than protocol messages to stdout. To check an installation:

```bash
python3 scripts/mcp_handshake_smoke.py lifecycle-mcp
```

This starts the server twice against a temporary database and reports whether the MCP handshake succeeds with clean stdout. If it fails:

1. Reinstall so the pinned MCP SDK (`mcp[cli]>=1.10,<2`) is used:
   ```bash
   uv tool install --force .
   ```

2. Re-add the MCP server:
   ```bash
   claude mcp add lifecycle lifecycle-mcp
   ```

3. Check that the server starts without errors:
   ```bash
   lifecycle-mcp
   ```

**Server Not Found**

If the `lifecycle-mcp` command is not found after installation:

1. Verify installation completed successfully
2. Check that the entry point is registered in `pyproject.toml`
3. Try reinstalling with `pip install -e .`

### Database Issues

**Database Lock Errors**

If you see database lock errors, ensure only one instance of the server is running and that the database file has proper permissions.

**Schema Initialization**

The database schema is automatically created on first run. If you need to reset the database, simply delete the SQLite file (default: `lifecycle.db`).

## Development

### Using uv (Recommended)
```bash
# Install dependencies
uv sync

# Run the server directly
uv run server.py

# Test with Claude Code
claude mcp add lifecycle $(which uv) -- --directory $(pwd) run server.py
```

### Using pip (Traditional)
```bash
# Install in development mode
pip install -e .

# Run the server
lifecycle-mcp

# Test with Claude Code
claude mcp add lifecycle lifecycle-mcp
```

## Building Desktop Extension (.dxt)

To create a Desktop Extension package for one-click installation:

```bash
# Build the .dxt file
make build-dxt
# or
python build_dxt.py
```

This creates `lifecycle-mcp-1.0.0.dxt` which users can double-click to install in Claude Desktop.
