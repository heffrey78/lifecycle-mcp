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

The server exposes 39 MCP tools across 7 handler modules for comprehensive lifecycle management. Every tool rejects fields it does not declare, and the error names the field.

### Tool List
**Requirements**
- `create_requirement` - Create new requirements from interview data
- `update_requirement` - Edit a requirement's content (a reason is required at Approved or later)
- `update_requirement_status` - Move requirements through lifecycle states
- `delete_requirement` - Delete a Draft requirement created by mistake
- `query_requirements` - Search and filter requirements
- `query_requirements_json` - Query requirements as structured JSON
- `get_requirement_details` - Get full requirement with relationships
- `trace_requirement` - Trace requirement through implementation

**Tasks**
- `create_task` - Create implementation tasks from requirements
- `update_task` - Edit a task's content, move it to another parent or change its requirements
- `update_task_status` - Update task progress
- `delete_task` - Delete a Not Started task created by mistake
- `query_tasks` - Search and filter tasks
- `query_tasks_json` - Query tasks as structured JSON
- `get_task_details` - Get full task details with dependencies
- `sync_task_from_github` - Sync individual task from GitHub issue changes
- `bulk_sync_github_tasks` - Sync all tasks with their GitHub issues

**Architecture decisions**
- `create_architecture_decision` - Record architecture decisions (ADRs)
- `update_architecture` - Edit a Proposed architecture decision
- `update_architecture_status` - Update architecture decision status
- `delete_architecture` - Delete a Proposed architecture decision created by mistake
- `query_architecture_decisions` - Search and filter architecture decisions
- `query_architecture_decisions_json` - Query architecture decisions as structured JSON
- `get_architecture_details` - Get full architecture decision details
- `add_architecture_review` - Add review comments to architecture decisions

**Relationships and history**
- `create_relationship` - Link two records (dependencies, refinements, blocks and more)
- `delete_relationship` - Remove a link between two records
- `query_relationships` - Query links: one record's links by direction and type, or every link as JSON for a graph
- `get_entity_history` - Show how a record changed: creation, edits with before and after values, status changes, comments and deletion

**Status, interviews and export**
- `get_project_status` - Get project health metrics and dashboards
- `get_project_metrics` - Get structured project metrics for programmatic use
- `start_requirement_interview` - Start interactive requirement gathering
- `continue_requirement_interview` - Continue requirement interview sessions
- `start_architectural_conversation` - Start interactive architecture discussions
- `continue_architectural_conversation` - Continue architecture conversations
- `export_project_documentation` - Export comprehensive markdown documentation
- `create_architectural_diagrams` - Generate Mermaid diagrams for project visualization

### Editing, Deleting and History

These rules apply to `update_requirement`, `update_task`, `update_architecture` and the delete tools:

- **Edits happen in place.** Update tools change content only; status moves stay with the `update_*_status` tools, and record IDs never change.
- **Every change is recorded.** Each changed field is logged with its before and after values, the actor and the reason. `get_entity_history` shows the log.
- **Revisions guard against lost updates.** Each record has a revision, shown in its details, that goes up by one with every update that changes something. Pass `if_revision` to have the update refused, with nothing written, when the record has changed since you read it.
- **Approved requirements need a reason.** Editing a requirement at Approved or later requires `reason`. The requirement then shows as *Changed Since Last Review* in `get_requirement_details`, `trace_requirement` and `get_project_status`, listing the edited fields.
- **The next status change is the acknowledgement.** There is no separate acknowledgement step: the requirement's next status transition clears the flag, and that transition's comment records the review.
- **Decided architecture is not rewritten.** Architecture decisions can be edited only while Proposed. To change a decided one, record a new decision with `create_architecture_decision` and move the old one to Superseded.
- **Deleting is for mistakes.** Only Draft requirements, Not Started tasks and Proposed architecture decisions can be deleted, and only when nothing depends on them. Refusals name the blocking records. A deleted record's own links go with it, and its history remains.

#### `get_entity_history`
Show how a requirement, task or architecture decision changed over time, oldest first.

**Parameters:**
- `entity_id` (required): Requirement, task or architecture decision ID

**Returns:** Creation, field edits with before and after values and reasons, status changes, comments and deletion. Still available after the record is deleted.

### Requirement Management

#### `create_requirement`
Create new requirements from interview data or analysis.

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
Move requirements through their lifecycle with validation.

**Parameters:**
- `requirement_id` (required): Requirement ID (e.g., "REQ-0001-FUNC-00")
- `new_status` (required): Target status - "Draft", "Under Review", "Approved", "Architecture", "Ready", "Implemented", "Validated", "Deprecated"
- `comment` (optional): Review comment or justification

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

#### `get_requirement_details`
Get comprehensive requirement information including all relationships.

**Parameters:**
- `requirement_id` (required): Requirement ID

**Returns:** Detailed report with basic info, problem definition, functional requirements, acceptance criteria, and linked tasks.

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

#### `delete_requirement`
Delete a Draft requirement created by mistake.

**Parameters:**
- `requirement_id` (required): Requirement ID

Refused when the requirement is past Draft (move it to Deprecated instead) or when tasks, architecture decisions or other requirements link to it.

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
- `task_id` (required): Task ID (e.g., "TASK-0001-00-00")
- `new_status` (required): New status - "Not Started", "In Progress", "Blocked", "Complete", "Abandoned"
- `comment` (optional): Status update comment
- `assignee` (optional): New assignee

#### `query_tasks`
Search and filter tasks by various criteria.

**Parameters:**
- `status` (optional): Filter by status
- `priority` (optional): Filter by priority level
- `assignee` (optional): Filter by assignee
- `requirement_id` (optional): Filter by linked requirement

#### `get_task_details`
Get comprehensive task information including dependencies and relationships.

**Parameters:**
- `task_id` (required): Task ID

**Returns:** Detailed report with basic info, description, acceptance criteria, and linked requirements.

#### `sync_task_from_github`
Sync individual task from GitHub issue changes with conflict detection.

**Parameters:**
- `task_id` (required): Task ID to sync with its linked GitHub issue

**Returns:** Sync status and any updates applied from GitHub issue data.

#### `bulk_sync_github_tasks`
Sync all tasks with their GitHub issues in batch operation.

**Parameters:** None

**Returns:** Summary of sync operations performed across all tasks with GitHub issue links.

#### `update_task`
Edit a task's content, move it under another parent or change the requirements it implements. The task ID never changes.

**Parameters:**
- `task_id` (required): Task ID
- `title`, `priority`, `effort`, `user_story`, `acceptance_criteria`, `assignee`, `implementation_plan`, `test_plan`, `definition_of_done` (optional): New values, with the same types as in `create_task`
- `parent_task_id` (optional): New parent task; an empty string makes it a top-level task. A task cannot become its own parent or move under one of its subtasks
- `requirement_ids` (optional): Replaces the requirements the task implements; requirements being added must be approved, as in `create_task`
- `reason`, `actor`, `if_revision` (optional): As in `update_requirement`

Pass at least one field to change. Changes are not pushed to a linked GitHub issue.

#### `delete_task`
Delete a Not Started task created by mistake.

**Parameters:**
- `task_id` (required): Task ID

Refused when the task has started (mark it Abandoned instead), has subtasks, has tasks depending on it or is linked to a GitHub issue.

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
Update the status of an architecture decision with validation.

**Parameters:**
- `architecture_id` (required): Architecture ID (e.g., "ADR-0001")
- `new_status` (required): New status - "Proposed", "Accepted", "Rejected", "Deprecated", "Superseded", "Draft", "Under Review", "Approved", "Implemented"
- `comment` (optional): Status change comment

#### `query_architecture_decisions`
Search and filter architecture decisions by various criteria.

**Parameters:**
- `status` (optional): Filter by status
- `type` (optional): Filter by type (ADR, TDD, INTG)
- `requirement_id` (optional): Filter by linked requirement
- `search_text` (optional): Text search in title and context

#### `get_architecture_details`
Get comprehensive architecture decision information including all relationships and reviews.

**Parameters:**
- `architecture_id` (required): Architecture ID

**Returns:** Detailed report with basic info, context, decision details, drivers, options, consequences, linked requirements, and review history.

#### `add_architecture_review`
Add review comments to architecture decisions.

**Parameters:**
- `architecture_id` (required): Architecture ID
- `comment` (required): Review comment
- `reviewer` (optional): Reviewer name (default: "MCP User")

#### `update_architecture`
Edit an architecture decision's content while it is Proposed. Decisions in any other status are refused: record a new decision with `create_architecture_decision` and move the old one to Superseded.

**Parameters:**
- `architecture_id` (required): Architecture ID
- `title`, `context`, `decision`, `consequences`, `decision_drivers`, `considered_options`, `authors`, `deciders`, `implementation_notes`, `validation_criteria`, `risk_assessment` (at least one): New values, with the same types as in `create_architecture_decision`
- `reason`, `actor`, `if_revision` (optional): As in `update_requirement`

#### `delete_architecture`
Delete a Proposed architecture decision created by mistake.

**Parameters:**
- `architecture_id` (required): Architecture ID

Refused when the decision is past Proposed (reject or supersede it instead), when another decision is superseded by it or when records other than its own requirement links point to it.

### Project Monitoring

#### `get_project_status`
Get comprehensive project health metrics and dashboards.

**Parameters:**
- `include_blocked` (optional): Include blocked items analysis (default: true)

**Returns:** Dashboard with requirement overview, task statistics, completion percentages, and blocked items analysis.

### Interactive Interview Tools

#### `start_requirement_interview`
Start an interactive requirement gathering interview session.

**Parameters:**
- `project_context` (optional): Description of the project or system
- `stakeholder_role` (optional): Role of the person being interviewed

**Returns:** Session ID and initial questions to guide requirement gathering.

**Example:**
```json
{
  "project_context": "E-commerce platform modernization",
  "stakeholder_role": "Product Manager"
}
```

#### `continue_requirement_interview`
Continue an active interview session by providing answers to questions.

**Parameters:**
- `session_id` (required): Interview session ID from start_requirement_interview
- `answers` (required): Object containing answers to the current questions

**Returns:** Next set of questions or completion summary with created requirement.

**Example:**
```json
{
  "session_id": "a1b2c3d4",
  "answers": {
    "current_problem": "Users struggle with complex checkout process",
    "desired_outcome": "Streamlined one-click checkout experience",
    "success_criteria": "Checkout completion rate increases by 25%"
  }
}
```

**Interview Flow:**
1. **Problem Identification**: Understanding the current challenge
2. **Solution Definition**: Defining the desired outcome and constraints
3. **Details Gathering**: Collecting priority, type, and technical details
4. **Validation**: Establishing acceptance criteria and success metrics
5. **Completion**: Automatic requirement creation with interview summary

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
- `{project_name}-tasks.md` - Task documentation grouped by status with linked requirements
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
- `diagram_type` (optional): Type of diagram - "requirements", "tasks", "architecture", "full_project", "directory_structure", "dependencies" (default: "full_project")
- `requirement_ids` (optional): Array of specific requirement IDs to include
- `include_relationships` (optional): Include relationship arrows in diagrams (default: true)
- `output_format` (optional): Output format - "mermaid", "markdown_with_mermaid" (default: "mermaid")
- `interactive` (optional): Start interactive conversation for complex diagrams (default: false)

**Returns:** Mermaid diagram code or markdown-wrapped diagram.

**Diagram Types:**
- **requirements**: Flowchart showing requirement hierarchy by type with status colors
- **tasks**: Task hierarchy with parent-child relationships and status indicators
- **architecture**: Architecture decisions with status-based styling
- **full_project**: High-level overview showing relationships between requirements, tasks, and architecture
- **directory_structure**: Project directory structure visualization
- **dependencies**: Task dependency graph showing blocking relationships

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

### Interactive Architectural Conversation Tools

#### `start_architectural_conversation`
Start an interactive conversation for complex architectural diagram generation.

**Parameters:**
- `project_context` (optional): Description of the project or system
- `diagram_purpose` (optional): Purpose and goals for the diagram
- `complexity_level` (optional): Conversation complexity - "simple", "medium", "complex" (default: "medium")

**Returns:** Session ID and contextual questions based on complexity level.

**Complexity Levels:**
- **Simple**: Basic component and relationship questions
- **Medium**: Architectural challenges, stakeholders, and detail level questions
- **Complex**: Deep architectural patterns, compliance, security, and performance considerations

#### `continue_architectural_conversation`
Continue an active architectural conversation session with responses.

**Parameters:**
- `session_id` (required): Conversation session ID from start_architectural_conversation
- `responses` (required): Object containing responses to current questions

**Returns:** Next questions or completion with generated diagram.

**Conversation Flow:**
1. **Context Gathering**: Understanding architectural needs and stakeholders
2. **Diagram Specification**: Determining optimal diagram type and focus
3. **Detail Refinement**: Visual preferences and emphasis areas
4. **Completion**: Automatic diagram generation with conversation summary

**Example:**
```json
{
  "session_id": "a1b2c3d4",
  "responses": {
    "main_challenge": "Visualizing microservice dependencies for new team members",
    "stakeholders": "Development team and system architects",
    "detail_level": "High-level overview with key integration points"
  }
}
```

## Database Schema

The server maintains a comprehensive SQLite database with the following key entities:

- **Requirements**: Central entity with lifecycle states (Draft → Under Review → Approved → Architecture → Ready → Implemented → Validated → Deprecated)
- **Tasks**: Implementation work items with hierarchical structure (TASK-XXXX-YY-ZZ format)
- **Architecture**: ADRs and technical design documents
- **Relationships**: Many-to-many links between requirements, tasks, and architecture
- **Events**: Automatic logging of lifecycle events and status changes
- **Reviews**: Comments and feedback on requirements and tasks

## Entity ID Formats

- **Requirements**: `REQ-XXXX-TYPE-VV` (e.g., REQ-0001-FUNC-00)
- **Tasks**: `TASK-XXXX-YY-ZZ` (e.g., TASK-0001-00-00)
- **Architecture**: `ADR-XXXX` (e.g., ADR-0001)

## Environment Variables

- `LIFECYCLE_DB`: Path to SQLite database file (default: "./lifecycle.db")
- `LIFECYCLE_GITHUB`: Set to `on` to create and sync a GitHub issue for each task (default: off). Requires an authenticated `gh` CLI and a github.com `origin` remote in the server's working directory. When off, the server never runs `gh` or `git`.
- `LIFECYCLE_CALL_LOG`: Path to a file where the server appends one JSON line per tool call: tool name, argument names (not values), duration, whether it failed and response size. Off by default. `scripts/tool_usage_report.py` summarises these logs.

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
