#!/usr/bin/env python3
"""
Task Handler for MCP Lifecycle Management Server
Handles all task-related operations
"""

import json
from datetime import datetime, timezone
from typing import Any

from mcp.types import TextContent

from ..github_utils import GitHubUtils
from .base_handler import (
    EDIT_OPTION_PROPERTIES,
    STATUS_ID_LIST_PROPERTY,
    BaseHandler,
    DeleteRefused,
    EditRefused,
    RevisionConflict,
    StatusChange,
    StatusRefused,
)

# Fields update_task changes directly; parent_task_id and requirement_ids are links and handled separately.
TASK_EDITABLE = (
    "title",
    "priority",
    "effort",
    "user_story",
    "acceptance_criteria",
    "assignee",
    "implementation_plan",
    "test_plan",
    "definition_of_done",
)
# Curated list fields (roadmap R6b), shown after the acceptance criteria in details and export: (column, title).
TASK_LIST_SECTIONS = (
    ("implementation_plan", "Implementation Plan"),
    ("test_plan", "Test Plan"),
    ("definition_of_done", "Definition of Done"),
)
TASK_JSON_FIELDS = ("acceptance_criteria", *(column for column, _ in TASK_LIST_SECTIONS))

# Requirement statuses tasks may be linked to, by create_task and update_task alike.
APPROVED_REQUIREMENT_STATUSES = ("Approved", "Architecture", "Ready", "Implemented", "Validated")

PARENT_OF_TASK_SQL = (
    "SELECT target_id FROM relationships WHERE source_type = 'task' AND source_id = ? "
    "AND target_type = 'task' AND relationship_type = 'parent'"
)
REQUIREMENTS_OF_TASK_SQL = (
    "SELECT source_id FROM relationships WHERE source_type = 'requirement' AND target_type = 'task' "
    "AND target_id = ? AND relationship_type = 'implements' ORDER BY source_id"
)
# Returns a row when the second task is the first task or one of its ancestors.
TASK_ANCESTOR_SQL = """
    WITH RECURSIVE ancestors(id) AS (
        SELECT ?
        UNION
        SELECT rel.target_id FROM relationships rel JOIN ancestors a ON rel.source_id = a.id
        WHERE rel.source_type = 'task' AND rel.target_type = 'task' AND rel.relationship_type = 'parent'
    )
    SELECT 1 FROM ancestors WHERE id = ?
"""

# Each task and a task it waits on: depends and requires links point dependent -> dependency, blocks links point
# blocker -> blocked (roadmap R7).
TASK_DEPENDENCIES_SQL = """
    SELECT source_id AS task_id, target_id AS dependency_id FROM relationships
    WHERE source_type = 'task' AND target_type = 'task' AND relationship_type IN ('depends', 'requires')
    UNION
    SELECT target_id, source_id FROM relationships
    WHERE source_type = 'task' AND target_type = 'task' AND relationship_type = 'blocks'
"""

# The tasks a task waits on that are not Complete, for the workflow rules (roadmap R8).
UNMET_DEPENDENCIES_SQL = f"""
    SELECT d.id, d.status FROM ({TASK_DEPENDENCIES_SQL}) dep JOIN tasks d ON d.id = dep.dependency_id
    WHERE dep.task_id = ? AND d.status != 'Complete'
    ORDER BY d.id
"""

# A task's subtasks that are neither Complete nor Abandoned, for the workflow rules (roadmap R8).
OPEN_SUBTASKS_SQL = """
    SELECT t.id, t.status FROM tasks t JOIN relationships rel ON rel.source_id = t.id
    WHERE rel.source_type = 'task' AND rel.target_type = 'task' AND rel.target_id = ?
      AND rel.relationship_type = 'parent' AND t.status NOT IN ('Complete', 'Abandoned')
    ORDER BY t.id
"""

# Records that depend on a task and therefore block deleting it. "blocks" links point blocker -> blocked.
TASK_DELETE_BLOCKERS = [
    (
        "subtasks",
        "SELECT source_id FROM relationships WHERE target_type = 'task' AND target_id = ? "
        "AND relationship_type = 'parent'",
    ),
    (
        "tasks depending on it",
        "SELECT source_id FROM relationships WHERE target_type = 'task' AND target_id = ? "
        "AND source_type = 'task' AND relationship_type IN ('depends', 'requires', 'informs') "
        "UNION SELECT target_id FROM relationships WHERE source_type = 'task' AND source_id = ? "
        "AND relationship_type = 'blocks'",
    ),
    (
        "GitHub issue",
        "SELECT '#' || github_issue_number FROM tasks WHERE id = ? "
        "AND github_issue_number IS NOT NULL AND github_issue_number != ''",
    ),
]


class TaskHandler(BaseHandler):
    """Handler for task-related MCP tools"""

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return task tool definitions"""
        tools = [
            {
                "name": "create_task",
                "description": "Create implementation task from requirement",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_ids": {"type": "array", "items": {"type": "string"}},
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                        "effort": {"type": "string", "enum": ["XS", "S", "M", "L", "XL"]},
                        "user_story": {"type": "string"},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "parent_task_id": {"type": "string"},
                        "assignee": {"type": "string"},
                        "implementation_plan": {"type": "array", "items": {"type": "string"}},
                        "test_plan": {"type": "array", "items": {"type": "string"}},
                        "definition_of_done": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["requirement_ids", "title", "priority"],
                },
            },
            {
                "name": "update_task_status",
                "description": "Update task progress; the comment on a move to Blocked is kept as the reason",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "task_ids": STATUS_ID_LIST_PROPERTY,
                        "new_status": {
                            "type": "string",
                            "enum": ["Not Started", "In Progress", "Blocked", "Complete", "Abandoned"],
                        },
                        "comment": {"type": "string"},
                        "assignee": {"type": "string"},
                    },
                    "required": ["new_status"],
                },
            },
            {
                "name": "query_tasks",
                "description": "Search and filter tasks",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "priority": {"type": "string"},
                        "assignee": {"type": "string"},
                        "requirement_id": {"type": "string"},
                        "ready": {
                            "type": "boolean",
                            "description": "Only Not Started tasks whose dependencies are all Complete, by priority",
                        },
                    },
                },
            },
            {
                "name": "update_task",
                "description": "Edit content, move under another parent or change requirements. The ID never changes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                        "effort": {"type": "string", "enum": ["XS", "S", "M", "L", "XL"]},
                        "user_story": {"type": "string"},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "assignee": {"type": "string"},
                        "implementation_plan": {"type": "array", "items": {"type": "string"}},
                        "test_plan": {"type": "array", "items": {"type": "string"}},
                        "definition_of_done": {"type": "array", "items": {"type": "string"}},
                        "parent_task_id": {"type": "string", "description": "Empty string makes it top-level"},
                        "requirement_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "description": "Replaces its requirements; added ones must be approved",
                        },
                        **EDIT_OPTION_PROPERTIES,
                    },
                    "required": ["task_id"],
                },
            },
        ]
        if GitHubUtils.is_github_enabled():
            # Opt-in feature: listed only when LIFECYCLE_GITHUB=on (ADR-0002).
            tools.append(
                {
                    "name": "sync_github_tasks",
                    "description": "Sync tasks from their GitHub issues: one task with task_id, else every linked task",
                    "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}},
                }
            )
        return tools

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_task":
                return await self._create_task(**arguments)
            elif tool_name == "update_task_status":
                return await self._update_task_status(**arguments)
            elif tool_name == "query_tasks":
                return self._query_tasks(**arguments)
            elif tool_name == "sync_github_tasks" and GitHubUtils.is_github_enabled():
                task_id = arguments.get("task_id")
                return await (self._sync_from_github(task_id) if task_id else self._bulk_sync_with_github())
            elif tool_name == "update_task":
                return self._update_task(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    def _delete_task(self, **params) -> list[TextContent]:
        """Delete a Not Started task that nothing depends on"""
        error = self._validate_required_params(params, ["task_id"])
        if error:
            return self._create_error_response(error)
        task_id = params["task_id"]
        try:
            removed = self._delete_entity(
                "tasks", "task", task_id, deletable_status="Not Started", blockers=TASK_DELETE_BLOCKERS
            )
        except (LookupError, DeleteRefused) as e:
            return self._create_error_response(str(e))
        return self._create_above_fold_response(
            "SUCCESS", f"Task {task_id} deleted", f"🗑️ Removed {removed} link(s) it owned"
        )

    def _update_task(self, **params) -> list[TextContent]:
        """Edit task content, move it to another parent or replace its requirement links; the ID never changes"""
        error = self._validate_required_params(params, ["task_id"])
        if error:
            return self._create_error_response(error)
        task_id = params["task_id"]
        changes = {name: params[name] for name in TASK_EDITABLE if name in params}
        if not changes and "parent_task_id" not in params and "requirement_ids" not in params:
            fields = ", ".join((*TASK_EDITABLE, "parent_task_id", "requirement_ids"))
            return self._create_error_response(f"Nothing to update: pass at least one of {fields}")

        def relink(cur, _before: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
            links = {}
            if "parent_task_id" in params:
                links.update(self._move_to_parent(cur, task_id, params["parent_task_id"] or None))
            if "requirement_ids" in params:
                links.update(self._replace_requirement_links(cur, task_id, params["requirement_ids"]))
            return links

        try:
            result = self._apply_edit(
                "tasks",
                "task",
                task_id,
                changes,
                editable=TASK_EDITABLE,
                json_fields=TASK_JSON_FIELDS,
                actor=params.get("actor") or "MCP User",
                reason=params.get("reason"),
                if_revision=params.get("if_revision"),
                relink=relink,
            )
        except (LookupError, RevisionConflict, EditRefused) as e:
            return self._create_error_response(str(e))
        return self._create_structured_response(
            "SUCCESS",
            f"Task {task_id} updated",
            {"id": task_id, "changed": result.changed, "revision": result.revision},
            self._describe_edit(result),
        )

    def _move_to_parent(self, cur, task_id: str, parent_id: str | None) -> dict[str, tuple[Any, Any]]:
        """Replace the task's parent link inside the edit transaction; parent_id None makes it top-level"""
        row = cur.execute(PARENT_OF_TASK_SQL, [task_id]).fetchone()
        current_id = row[0] if row else None
        if parent_id == current_id:
            return {}
        if parent_id == task_id:
            raise EditRefused(f"Task {task_id} cannot be its own parent")
        if parent_id is not None:
            if cur.execute("SELECT 1 FROM tasks WHERE id = ?", [parent_id]).fetchone() is None:
                raise EditRefused(f"Parent task {parent_id} not found")
            if cur.execute(TASK_ANCESTOR_SQL, [parent_id, task_id]).fetchone():
                raise EditRefused(
                    f"Task {parent_id} sits below {task_id} in the task hierarchy, so it cannot become its parent "
                    "(that would create a cycle)"
                )
        cur.execute(
            "DELETE FROM relationships WHERE source_type = 'task' AND source_id = ? "
            "AND target_type = 'task' AND relationship_type = 'parent'",
            [task_id],
        )
        if parent_id is not None:
            self._link("task", task_id, "task", parent_id, "parent", cursor=cur)
        return {"parent_task_id": (current_id, parent_id)}

    def _replace_requirement_links(self, cur, task_id: str, requirement_ids: list[str]) -> dict[str, tuple[Any, Any]]:
        """Make the task implement exactly these requirements inside the edit transaction"""
        wanted = sorted(set(requirement_ids))
        if not wanted:
            raise EditRefused(f"Task {task_id} must implement at least one requirement")
        current = [row[0] for row in cur.execute(REQUIREMENTS_OF_TASK_SQL, [task_id]).fetchall()]
        if wanted == current:
            return {}
        added = [req_id for req_id in wanted if req_id not in current]
        statuses = {}
        for req_id in added:
            row = cur.execute("SELECT status FROM requirements WHERE id = ?", [req_id]).fetchone()
            statuses[req_id] = row[0] if row else None
        error = self._requirement_gate_error(statuses, "link tasks to")
        if error:
            raise EditRefused(error)
        for req_id in current:
            if req_id not in wanted:
                cur.execute(
                    "DELETE FROM relationships WHERE source_type = 'requirement' AND source_id = ? "
                    "AND target_type = 'task' AND target_id = ? AND relationship_type = 'implements'",
                    [req_id, task_id],
                )
        for req_id in added:
            self._link("requirement", req_id, "task", task_id, "implements", cursor=cur)
        return {"requirement_ids": (json.dumps(current), json.dumps(wanted))}

    @staticmethod
    def _requirement_gate_error(statuses: dict[str, str | None], action: str) -> str | None:
        """Why tasks cannot be linked to these requirements (ID -> status, None when missing); None when they can"""
        missing = [req_id for req_id, status in statuses.items() if status is None]
        if missing:
            return f"Requirement {missing[0]} not found"
        unapproved = [
            f"- {req_id} (status: {status})"
            for req_id, status in statuses.items()
            if status not in APPROVED_REQUIREMENT_STATUSES
        ]
        if not unapproved:
            return None
        return (
            f"Cannot {action} unapproved requirements. The following requirements must be approved first:\n"
            + "\n".join(unapproved)
            + "\n\nRequirements must be in one of these states: "
            + ", ".join(sorted(APPROVED_REQUIREMENT_STATUSES))
        )

    async def _create_task(self, **params) -> list[TextContent]:
        """Create task linked to requirements"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_ids", "title", "priority"])
        if error:
            return self._create_error_response(error)

        # Tasks may only implement approved requirements
        statuses = {}
        for req_id in params["requirement_ids"]:
            rows = self.db.get_records("requirements", "status", "id = ?", [req_id])
            statuses[req_id] = rows[0]["status"] if rows else None
        error = self._requirement_gate_error(statuses, "create tasks for")
        if error:
            return self._create_error_response(error)

        try:
            # Get next task number
            task_number = self.db.get_next_id("tasks", "task_number")

            # Determine subtask number
            subtask_number = 0
            if params.get("parent_task_id"):
                # Subtasks share the parent's task number and take the next subtask number in use under it.
                # Counting the parent's current subtasks would reuse an ID once one is deleted or moved away.
                parent_info = self.db.get_records("tasks", "task_number", "id = ?", [params["parent_task_id"]])
                if not parent_info:
                    return self._create_error_response(f"Parent task {params['parent_task_id']} not found")
                task_number = parent_info[0]["task_number"]
                subtask_number = self.db.get_next_id("tasks", "subtask_number", "task_number = ?", [task_number])

            task_id = f"TASK-{task_number:04d}-{subtask_number:02d}-00"

            # Prepare task data (removed parent_task_id column)
            task_data = {
                "id": task_id,
                "task_number": task_number,
                "subtask_number": subtask_number,
                "version": 0,
                "title": params["title"],
                "priority": params["priority"],
                "effort": params.get("effort"),
                "user_story": params.get("user_story"),
                "acceptance_criteria": self._safe_json_dumps(params.get("acceptance_criteria", [])),
                "assignee": params.get("assignee"),
                "status": "Not Started",
                **{
                    column: self._safe_json_dumps(params[column])
                    for column, _ in TASK_LIST_SECTIONS
                    if column in params
                },
            }

            # Insert task
            self.db.insert_record("tasks", task_data)
            self._log_operation("task", task_id, "created", params.get("assignee") or "MCP User")

            # Create parent-child relationship if this is a subtask
            if params.get("parent_task_id"):
                self._link("task", task_id, "task", params["parent_task_id"], "parent")

            # Link to requirements
            for req_id in params["requirement_ids"]:
                self._link("requirement", req_id, "task", task_id, "implements")

            # Create GitHub issue if available
            github_url = None
            github_error = None
            if GitHubUtils.is_github_available():
                try:
                    github_title = f"{task_id}: {params['title']}"
                    github_body = GitHubUtils.format_task_body(task_data)

                    # Create labels based on priority and status
                    labels = [params["priority"].lower()]
                    if params.get("effort"):
                        labels.append(f"effort-{params['effort'].lower()}")

                    github_url = await GitHubUtils.create_github_issue(
                        title=github_title, body=github_body, labels=labels, assignee=params.get("assignee")
                    )

                    # Store GitHub issue metadata if created successfully
                    if github_url:
                        issue_number = GitHubUtils.extract_issue_number_from_url(github_url)
                        if issue_number:
                            # Get the created issue details for ETag storage
                            github_issue = await GitHubUtils.get_github_issue(issue_number)

                            github_data = {
                                "github_issue_number": issue_number,
                                "github_issue_url": github_url,
                                "github_last_sync": datetime.now(timezone.utc).isoformat(),
                                "github_etag": github_issue.get("etag") if github_issue else None,
                            }

                            self.db.update_record("tasks", github_data, "id = ?", [task_id])
                    else:
                        github_error = "GitHub issue creation returned no URL"

                except Exception as e:
                    github_error = f"GitHub issue creation failed: {str(e)}"
                    self.logger.warning(f"GitHub integration error for task {task_id}: {github_error}")
            else:
                github_error = GitHubUtils.unavailable_reason()

            # Create above-the-fold response
            key_info = f"Task {task_id} created"
            action_info = f"📋 {params['title']} | {params['priority']} | {params.get('effort', 'No effort specified')}"

            github_info = ""
            if github_url:
                github_info = f"🔗 GitHub: {github_url}"
            elif not GitHubUtils.is_github_enabled():
                github_info = f"GitHub: {github_error}"
            elif github_error:
                github_info = f"⚠️ GitHub: {github_error}"

            structured = {
                "id": task_id,
                "status": "Not Started",
                "requirement_ids": params["requirement_ids"],
                "parent_task_id": params.get("parent_task_id"),
                "github_issue_url": github_url,
            }
            return self._create_structured_response("SUCCESS", key_info, structured, action_info, github_info)

        except Exception as e:
            return self._create_error_response("Failed to create task", e)

    async def _update_task_status(self, **params) -> list[TextContent]:
        """Move one task, or each of task_ids, to new_status (roadmap R9)"""
        error = self._validate_required_params(params, ["new_status"])
        if error:
            return self._create_error_response(error)
        return await self._change_statuses(
            params,
            "task_id",
            "Task",
            "tasks",
            lambda task_id: self._change_task_status(task_id, params),
            "Failed to update task",
        )

    async def _change_task_status(self, task_id: str, params: dict[str, Any]) -> StatusChange:
        """Move one task to new_status with its assignee and comment, and sync its GitHub issue"""
        # Get current task with GitHub info
        current_tasks = self.db.get_records(
            "tasks", "status, assignee, github_issue_number, github_issue_url", "id = ?", [task_id]
        )

        if not current_tasks:
            raise StatusRefused("Task not found")

        current_task = dict(current_tasks[0])  # Convert Row to dict for .get() method
        current_status = current_task["status"]
        new_status = params["new_status"]
        # Workflow rules run before anything is written, so enforce leaves the task where it was (roadmap R8).
        warnings = self._rule_warnings(self._task_rule_reasons(task_id, current_status, new_status))

        # Update status and assignee. CURRENT_TIMESTAMP has to be SQL, not a bound value (F-42).
        assignments, values = "status = ?, updated_at = CURRENT_TIMESTAMP", [new_status]
        # The comment given with a move to Blocked is why it's blocked; leaving Blocked clears it (roadmap R7).
        if new_status != "Blocked":
            assignments += ", blocked_reason = NULL"
        elif params.get("comment") or current_status != "Blocked":
            assignments += ", blocked_reason = ?"
            values.append(params.get("comment"))
        if params.get("assignee"):
            assignments += ", assignee = ?"
            values.append(params["assignee"])
        self.db.execute_query(f"UPDATE tasks SET {assignments} WHERE id = ?", [*values, task_id])

        # Add comment if provided
        if params.get("comment"):
            self._add_review_comment("task", task_id, params["comment"])

        # Update GitHub issue if it exists using sync-safe operations
        github_updated = False
        github_error = None

        if current_task.get("github_issue_number") and GitHubUtils.is_github_available():
            try:
                # Prepare GitHub updates
                github_updates = {}

                # Map task status to GitHub state
                if new_status == "Complete":
                    github_updates["state"] = "closed"
                elif new_status in ["Not Started", "In Progress", "Blocked"]:
                    github_updates["state"] = "open"

                # Prepare comment
                github_comment = f"Task status updated from '{current_status}' to '{new_status}'"
                if params.get("comment"):
                    github_comment += f"\n\n{params['comment']}"
                github_updates["comment"] = github_comment

                # Update assignee if changed
                if params.get("assignee") and params["assignee"] != current_task.get("assignee"):
                    github_updates["assignees"] = [params["assignee"]] if params["assignee"] else []

                # Use sync-safe update with current ETag
                current_etag = current_task.get("github_etag")
                success, error_msg, updated_issue = await GitHubUtils.update_github_issue_safe(
                    str(current_task["github_issue_number"]), github_updates, expected_etag=current_etag
                )

                if success and updated_issue:
                    github_updated = True
                    # Update stored ETag and sync timestamp
                    self.db.update_record(
                        "tasks",
                        {"github_etag": updated_issue.get("etag"), "github_last_sync": datetime.now().isoformat()},
                        "id = ?",
                        [task_id],
                    )
                else:
                    github_error = error_msg or "GitHub update failed"
                    self.logger.warning(f"GitHub sync failed for task {task_id}: {github_error}")

            except Exception as e:
                github_error = f"GitHub update error: {str(e)}"
                self.logger.error(f"GitHub integration error: {github_error}")
        else:
            if current_task.get("github_issue_number"):
                github_error = GitHubUtils.unavailable_reason()

        github_info = ""
        if github_updated:
            github_info = f"🔗 GitHub issue #{current_task['github_issue_number']} synced"
        elif github_error:
            github_info = f"⚠️ GitHub sync failed: {github_error}"

        return StatusChange(task_id, current_status, new_status, note=github_info, warnings=warnings)

    def _task_rule_reasons(self, task_id: str, current_status: str, new_status: str) -> list[str]:
        """Why this move is risky: unfinished dependencies, open subtasks, or a skipped or reopened task (R8)"""
        reasons = self._dependency_reasons(task_id, new_status)
        if new_status == "Complete":
            open_subtasks = self.db.execute_query(OPEN_SUBTASKS_SQL, [task_id], fetch_all=True, row_factory=True) or []
            if open_subtasks:
                listed = ", ".join(f"{row['id']} ({row['status']})" for row in open_subtasks)
                reasons.append(f"Subtasks not finished: {listed}")
            if current_status == "Not Started":
                reasons.append("Completing a task that was never started")
            elif current_status == "Blocked":
                reasons.append("Completing a task that is still Blocked")
        elif current_status == "Complete":
            reasons.append(f"Reopening a Complete task as {new_status}")
        return reasons

    def _dependency_reasons(self, task_id: str, new_status: str) -> list[str]:
        """Why starting or completing this task is risky: the tasks it waits on are not Complete (roadmap R8)"""
        if new_status not in ("In Progress", "Complete"):
            return []
        rows = self.db.execute_query(UNMET_DEPENDENCIES_SQL, [task_id], fetch_all=True, row_factory=True) or []
        unfinished = [f"{row['id']} ({row['status']})" for row in rows if row["status"] != "Abandoned"]
        abandoned = [row["id"] for row in rows if row["status"] == "Abandoned"]
        reasons = []
        if unfinished:
            reasons.append(f"Dependencies not finished: {', '.join(unfinished)}")
        if abandoned:
            reasons.append(
                f"Dependencies abandoned: {', '.join(abandoned)}. Drop the link with delete_relationship, "
                "or abandon this task too"
            )
        return reasons

    def _query_tasks(self, **params) -> list[TextContent]:
        """Query tasks with filters"""
        try:
            where_clauses = []
            where_params = []

            if params.get("requirement_id"):
                where_clauses.append(
                    "t.id IN (SELECT target_id FROM relationships WHERE source_type = 'requirement' AND source_id = ? "
                    "AND target_type = 'task' AND relationship_type = 'implements')"
                )
                where_params.append(params["requirement_id"])

            for column in ("status", "priority", "assignee"):
                if params.get(column):
                    where_clauses.append(f"t.{column} = ?")
                    where_params.append(params[column])

            order_by = "t.priority, t.created_at DESC"
            if params.get("ready"):
                # Ready to start: Not Started, and every task it waits on is Complete (roadmap R7)
                where_clauses.append(
                    f"t.status = 'Not Started' AND NOT EXISTS (SELECT 1 FROM ({TASK_DEPENDENCIES_SQL}) dep "
                    "JOIN tasks d ON d.id = dep.dependency_id WHERE dep.task_id = t.id AND d.status != 'Complete')"
                )
                order_by = "t.priority, t.task_number, t.subtask_number"

            where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            tasks = self.db.execute_query(
                f"SELECT t.* FROM tasks t {where} ORDER BY {order_by}",
                where_params,
                fetch_all=True,
                row_factory=True,
            )

            # The full records, JSON fields parsed, as structured data next to the list (roadmap R10)
            structured = {"tasks": self._record_dicts(tasks, TASK_JSON_FIELDS), "count": len(tasks)}

            if not tasks:
                return self._create_structured_response(
                    "INFO", "No tasks found", structured, "Try adjusting search criteria"
                )

            # Build filter description for above-the-fold
            filters = []
            if params.get("status"):
                filters.append(f"status: {params['status']}")
            if params.get("priority"):
                filters.append(f"priority: {params['priority']}")
            if params.get("assignee"):
                filters.append(f"assignee: {params['assignee']}")
            if params.get("requirement_id"):
                filters.append(f"requirement: {params['requirement_id']}")
            if params.get("ready"):
                filters.append("ready to start")
            filter_desc = " | ".join(filters) if filters else "all tasks"

            # Build detailed list
            task_list = []
            for task in tasks:
                task_info = f"- {task['id']}: {task['title']} [{task['status']}] {task['priority']}"
                if task["assignee"]:
                    task_info += f" (👤 {task['assignee']})"
                task_list.append(task_info)

            key_info = self._format_count_summary("task", len(tasks), filter_desc)
            details = "\n".join(task_list)

            return self._create_structured_response("SUCCESS", key_info, structured, "", details)

        except Exception as e:
            return self._create_error_response("Failed to query tasks", e)

    async def _sync_from_github(self, task_id: str) -> list[TextContent]:
        """Sync task from GitHub issue changes"""
        try:
            # Get current task with GitHub info
            tasks = self.db.get_records("tasks", "*", "id = ?", [task_id])

            if not tasks:
                return self._create_error_response("Task not found")

            task = dict(tasks[0])  # Convert Row to dict for .get() method
            github_issue_number = task.get("github_issue_number")

            if not github_issue_number:
                return self._create_error_response("Task has no associated GitHub issue")

            # Use GitHubUtils sync method
            success, sync_message, github_issue = await GitHubUtils.sync_task_with_github(
                task,
                force_sync=False,  # task is already a dict
            )

            # Handle conflicts as warnings, not errors
            if not success and "conflicts detected" in sync_message.lower():
                key_info = f"Sync conflicts for task {task_id}"
                return self._create_above_fold_response("WARNING", key_info, sync_message)

            # Handle other failures as errors
            if not success:
                return self._create_error_response(f"GitHub sync failed: {sync_message}")

            # Apply GitHub changes to local task if needed
            updates_applied = []

            if github_issue:
                # Map GitHub state to task status
                github_state = github_issue.get("state", "")
                current_status = task.get("status", "")

                new_status = None
                if github_state == "closed" and current_status != "Complete":
                    new_status = "Complete"
                elif github_state == "open" and current_status == "Complete":
                    new_status = "In Progress"

                if new_status:
                    self.db.update_record(
                        "tasks",
                        {
                            "status": new_status,
                            "github_last_sync": datetime.now(timezone.utc).isoformat(),
                            "github_etag": github_issue.get("etag"),
                        },
                        "id = ?",
                        [task_id],
                    )
                    updates_applied.append(f"Status: {current_status} → {new_status}")

                # Update assignee if changed
                github_assignees = [a.get("login", "") for a in github_issue.get("assignees", [])]
                github_assignee = github_assignees[0] if github_assignees else None
                current_assignee = task.get("assignee")

                if github_assignee != current_assignee:
                    self.db.update_record("tasks", {"assignee": github_assignee}, "id = ?", [task_id])
                    updates_applied.append(f"Assignee: {current_assignee or 'None'} → {github_assignee or 'None'}")

            # Create response
            if updates_applied:
                key_info = f"Task {task_id} synced from GitHub"
                action_info = " | ".join(updates_applied)
                return self._create_above_fold_response("SUCCESS", key_info, action_info)
            else:
                key_info = f"Task {task_id} already in sync"
                return self._create_above_fold_response("INFO", key_info, sync_message)

        except Exception as e:
            return self._create_error_response("Failed to sync from GitHub", e)

    async def _bulk_sync_with_github(self, **params) -> list[TextContent]:
        """Sync all tasks with GitHub issues"""
        try:
            # Get all tasks with GitHub issues
            tasks_with_github = self.db.get_records(
                "tasks",
                "id, title, status, github_issue_number, github_last_sync",
                "github_issue_number IS NOT NULL AND github_issue_number != ''",
                [],
                "created_at DESC",
            )

            if not tasks_with_github:
                return self._create_above_fold_response("INFO", "No tasks with GitHub issues found")

            # Check sync status for each task
            sync_results = []
            conflicts_found = []
            updates_applied = []

            for task in tasks_with_github:
                try:
                    success, sync_message, github_issue = await GitHubUtils.sync_task_with_github(
                        dict(task), force_sync=False
                    )

                    if not success:
                        if "conflicts detected" in sync_message.lower():
                            conflicts_found.append(f"{task['id']}: {sync_message}")
                        else:
                            sync_results.append(f"❌ {task['id']}: {sync_message}")
                    elif "in sync" in sync_message.lower():
                        sync_results.append(f"✅ {task['id']}: {sync_message}")
                    else:
                        # Apply updates if any changes detected
                        task_updates = []

                        if github_issue:
                            # Update status if changed
                            github_state = github_issue.get("state", "")
                            current_status = task.get("status", "")

                            new_status = None
                            if github_state == "closed" and current_status != "Complete":
                                new_status = "Complete"
                            elif github_state == "open" and current_status == "Complete":
                                new_status = "In Progress"

                            update_data = {
                                "github_last_sync": datetime.now(timezone.utc).isoformat(),
                                "github_etag": github_issue.get("etag"),
                            }

                            if new_status:
                                update_data["status"] = new_status
                                task_updates.append(f"Status: {current_status} → {new_status}")

                            # Update assignee if changed
                            github_assignees = [a.get("login", "") for a in github_issue.get("assignees", [])]
                            github_assignee = github_assignees[0] if github_assignees else None
                            current_assignee = task.get("assignee")

                            if github_assignee != current_assignee:
                                update_data["assignee"] = github_assignee
                                from_assignee = current_assignee or "None"
                                to_assignee = github_assignee or "None"
                                task_updates.append(f"Assignee: {from_assignee} → {to_assignee}")

                            if task_updates:
                                self.db.update_record("tasks", update_data, "id = ?", [task["id"]])
                                updates_applied.append(f"🔄 {task['id']}: {' | '.join(task_updates)}")
                            else:
                                sync_results.append(f"✅ {task['id']}: Updated sync metadata")

                except Exception as e:
                    sync_results.append(f"❌ {task['id']}: Error - {str(e)}")

            # Build summary
            total_tasks = len(tasks_with_github)
            updates_count = len(updates_applied)
            conflicts_count = len(conflicts_found)

            key_info = f"Synced {total_tasks} GitHub task(s)"
            action_info = f"🔄 {updates_count} updated | ⚠️ {conflicts_count} conflicts"

            # Build detailed report
            details = []
            if updates_applied:
                details.append("## Updated Tasks")
                details.extend(updates_applied)
                details.append("")

            if conflicts_found:
                details.append("## Conflicts Detected")
                details.extend(conflicts_found)
                details.append("")

            if sync_results:
                details.append("## All Sync Results")
                details.extend(sync_results)

            report = "\n".join(details)

            return self._create_above_fold_response("SUCCESS", key_info, action_info, report)

        except Exception as e:
            return self._create_error_response("Failed to bulk sync with GitHub", e)

    def _get_task_details(self, **params) -> list[TextContent]:
        """Get full task details"""
        # Validate required parameters
        error = self._validate_required_params(params, ["task_id"])
        if error:
            return self._create_error_response(error)

        try:
            # Get task
            tasks = self.db.get_records("tasks", "*", "id = ?", [params["task_id"]])

            if not tasks:
                return self._create_error_response("Task not found")

            task = dict(tasks[0])  # Convert Row to dict for .get() method

            # Build report
            task_info = f"""# Task Details: {task["id"]}

## Basic Information
- **Title**: {task["title"]}
- **Status**: {task["status"]}
- **Priority**: {task["priority"]}
- **Effort**: {task["effort"] or "Not specified"}
- **Assignee**: {task["assignee"] or "Unassigned"}
- **Created**: {task["created_at"]}
- **Updated**: {task["updated_at"]}
- **Revision**: {task["revision"]}"""

            if task["status"] == "Blocked":
                task_info += f"\n- **Blocked Reason**: {task['blocked_reason'] or 'Not given'}"

            if task["github_issue_number"]:
                task_info += f"\n- **GitHub Issue**: #{task['github_issue_number']} - {task['github_issue_url']}"

            task_info += f"""

## Description
{task["user_story"] or "No user story provided"}

## Acceptance Criteria
"""

            if task["acceptance_criteria"]:
                criteria = self._safe_json_loads(task["acceptance_criteria"])
                if criteria:
                    for criterion in criteria:
                        task_info += f"- {criterion}\n"
                else:
                    task_info += "No acceptance criteria defined\n"
            else:
                task_info += "No acceptance criteria defined\n"

            task_info += self._format_sections(task, TASK_LIST_SECTIONS, "\n## {title}\n{body}")

            # Get linked requirements
            requirements = self.db.execute_query(
                """
                SELECT r.id, r.title FROM requirements r
                JOIN relationships rel ON rel.source_id = r.id
                WHERE rel.source_type = 'requirement' AND rel.target_type = 'task'
                  AND rel.target_id = ? AND rel.relationship_type = 'implements'
            """,
                [params["task_id"]],
                fetch_all=True,
                row_factory=True,
            )

            if requirements:
                task_info += f"\n## Linked Requirements ({len(requirements)})\n"
                for req in requirements:
                    task_info += f"- {req['id']}: {req['title']}\n"

            # Get subtasks if this is a parent task
            # Query relationships table for child tasks
            child_relationship_records = self.db.get_records(
                "relationships",
                "source_id",
                "target_type = 'task' AND target_id = ? AND relationship_type = 'parent'",
                [params["task_id"]],
            )

            subtasks = []
            if child_relationship_records:
                child_task_ids = [r["source_id"] for r in child_relationship_records]
                for task_id in child_task_ids:
                    task_records = self.db.get_records("tasks", "id, title, status", "id = ?", [task_id])
                    if task_records:
                        subtasks.extend(task_records)

            if subtasks:
                task_info += f"\n## Subtasks ({len(subtasks)})\n"
                for subtask in subtasks:
                    task_info += f"- {subtask['id']}: {subtask['title']} [{subtask['status']}]\n"

            # Show parent task if this is a subtask
            # Query relationships table for parent tasks
            parent_relationship_records = self.db.get_records(
                "relationships",
                "target_id",
                "source_type = 'task' AND source_id = ? AND relationship_type = 'parent'",
                [params["task_id"]],
            )

            if parent_relationship_records:
                parent_task_id = parent_relationship_records[0]["target_id"]
                parent_tasks = self.db.get_records("tasks", "id, title, status", "id = ?", [parent_task_id])

                if parent_tasks:
                    parent = dict(parent_tasks[0])  # Convert Row to dict for consistency
                    task_info += "\n## Parent Task\n"
                    task_info += f"- {parent['id']}: {parent['title']} [{parent['status']}]\n"

            # Tasks this task waits on, and tasks waiting on it (roadmap R7)
            task_info += self._format_linked(
                "Depends On",
                f"SELECT t.id, t.title, t.status FROM tasks t JOIN ({TASK_DEPENDENCIES_SQL}) dep "
                "ON dep.dependency_id = t.id WHERE dep.task_id = ? ORDER BY t.id",
                task["id"],
            )
            task_info += self._format_linked(
                "Blocks",
                f"SELECT t.id, t.title, t.status FROM tasks t JOIN ({TASK_DEPENDENCIES_SQL}) dep "
                "ON dep.task_id = t.id WHERE dep.dependency_id = ? ORDER BY t.id",
                task["id"],
            )

            # Architecture decisions this task implements (roadmap R9)
            task_info += self._format_linked(
                "Implements Decisions",
                "SELECT a.id, a.title, a.status FROM architecture a JOIN relationships rel ON rel.target_id = a.id "
                "WHERE rel.source_type = 'task' AND rel.source_id = ? AND rel.target_type = 'architecture' "
                "AND rel.relationship_type = 'implements' ORDER BY a.id",
                task["id"],
            )

            task_info += self._format_comments("task", task["id"])

            # Create above-the-fold summary
            key_info = self._format_status_summary("Task", task["id"], task["status"])
            action_info = f"📋 {task['title']} | {task['priority']} | {task['effort'] or 'No effort'}"
            if task["assignee"]:
                action_info += f" | 👤 {task['assignee']}"

            return self._create_above_fold_response("INFO", key_info, action_info, task_info)

        except Exception as e:
            return self._create_error_response("Failed to get task details", e)
