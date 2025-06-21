# Lifecycle MCP Server

A Model Context Protocol (MCP) server for comprehensive software lifecycle management. This server provides structured tracking of requirements, tasks, and architecture decisions through a SQLite database with full traceability and automated state management.

## Features

- **Requirements Management**: Create and manage software requirements with validation and lifecycle tracking
- **Task Management**: Track implementation tasks with hierarchical structure and effort estimation
- **Architecture Decisions**: Record ADRs (Architecture Decision Records) with full context
- **Project Dashboards**: Real-time project health metrics and status reporting
- **Requirement Tracing**: Complete traceability from requirements through implementation
- **State Validation**: Automatic validation of lifecycle state transitions
- **Relationship Tracking**: Many-to-many relationships between requirements, tasks, and architecture

## Installation

```bash
pip install lifecycle-mcp
```

## Usage with Claude Code

```bash
claude mcp add lifecycle-mcp
```

Alternatively, reference the repository folder. Set the environment variable `LIFECYCLE_DB` to the desired location. Recommend one database per project.

```bash
claude mcp add lifecycle python3.10 {REPOSITORY FOLDER}/lifecycle_server.py -e LIFECYCLE_DB=./lifecycle.db
```

## Manual Configuration

Add to your MCP configuration:

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

## MCP Tools Reference

The server exposes 17 MCP tools for comprehensive lifecycle management:

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

## Development

```bash
# Install in development mode
pip install -e .

# Run the server
lifecycle-mcp

# Test with Claude Code
claude mcp add lifecycle-mcp
```