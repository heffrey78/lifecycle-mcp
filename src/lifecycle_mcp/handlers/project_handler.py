#!/usr/bin/env python3
"""
Project Handler for MCP Lifecycle Management Server
Projects: named groups of requirements and the purpose each group serves
"""

import json
import sqlite3
from typing import Any

from mcp.types import TextContent

from ..database_manager import DatabaseManager
from ..migrations import IS_LEAF_TASK
from .base_handler import EDIT_OPTION_PROPERTIES, BaseHandler, DeleteRefused, EditRefused, RevisionConflict

# Fields update_project can change. Closing a project has no gate, so status is an ordinary field here rather than a
# tool of its own.
PROJECT_EDITABLE = ("title", "purpose", "success_criteria", "out_of_scope", "status")
PROJECT_STATUSES = ("Active", "Closed")

# List fields, shown after the purpose in details and export: (column, title).
PROJECT_LIST_SECTIONS = (
    ("success_criteria", "Success Criteria"),
    ("out_of_scope", "Out of Scope"),
)
PROJECT_JSON_FIELDS = tuple(column for column, _ in PROJECT_LIST_SECTIONS)

# The IDs of the requirements in a project; one `?`, the project's ID. Membership is a requirement -> project part_of
# link and nothing else: tasks and decisions belong to a project through the requirement they implement or address.
# The one definition behind query_requirements(project_id), query_tasks(project_id), export and the dashboard.
PROJECT_REQUIREMENT_IDS_SQL = (
    "SELECT source_id FROM relationships WHERE source_type = 'requirement' AND target_type = 'project' "
    "AND target_id = ? AND relationship_type = 'part_of'"
)

# The projects a requirement belongs to; one `?`, the requirement's ID.
REQUIREMENT_PROJECTS_SQL = """
    SELECT p.id, p.title, p.status FROM projects p JOIN relationships rel ON rel.target_id = p.id
    WHERE rel.source_type = 'requirement' AND rel.source_id = ?
      AND rel.target_type = 'project' AND rel.relationship_type = 'part_of'
    ORDER BY p.id
"""

# A project's leaf tasks by status. DISTINCT because a task implementing two of its requirements is one task.
PROJECT_TASK_STATUS_SQL = f"""
    SELECT t.status, COUNT(DISTINCT t.id) AS count FROM relationships rel JOIN tasks t ON t.id = rel.target_id
    WHERE rel.source_type = 'requirement' AND rel.target_type = 'task' AND rel.relationship_type = 'implements'
      AND rel.source_id IN ({PROJECT_REQUIREMENT_IDS_SQL}) AND {IS_LEAF_TASK}
    GROUP BY t.status
"""

# The decisions a project's requirements address.
PROJECT_DECISIONS_SQL = f"""
    SELECT DISTINCT a.id, a.title, a.status FROM architecture a JOIN relationships rel ON rel.target_id = a.id
    WHERE rel.source_type = 'requirement' AND rel.target_type = 'architecture'
      AND rel.relationship_type = 'addresses' AND rel.source_id IN ({PROJECT_REQUIREMENT_IDS_SQL})
    ORDER BY a.id
"""


def project_requirements(db: DatabaseManager, project_id: str) -> list[Any]:
    """The requirements in a project, in the order export lists them"""
    return (
        db.execute_query(
            f"SELECT * FROM requirements WHERE id IN ({PROJECT_REQUIREMENT_IDS_SQL}) ORDER BY type, requirement_number",
            [project_id],
            fetch_all=True,
            row_factory=True,
        )
        or []
    )


def project_progress(db: DatabaseManager, project_id: str) -> dict[str, Any]:
    """How far a project's requirements and their tasks have got.

    Abandoned tasks are counted apart and left out of the total, as the dashboard leaves them out: they were decided
    against, not left undone.
    """
    by_status: dict[str, int] = {}
    for requirement in project_requirements(db, project_id):
        by_status[requirement["status"]] = by_status.get(requirement["status"], 0) + 1
    tasks = {
        row["status"]: row["count"]
        for row in db.execute_query(PROJECT_TASK_STATUS_SQL, [project_id], fetch_all=True, row_factory=True) or []
    }
    abandoned = tasks.pop("Abandoned", 0)
    return {
        "requirements": sum(by_status.values()),
        "requirements_by_status": by_status,
        "tasks": sum(tasks.values()),
        "tasks_complete": tasks.get("Complete", 0),
        "tasks_abandoned": abandoned,
    }


def describe_progress(progress: dict[str, Any]) -> str:
    """One line for a project's progress: its requirements by status, then its tasks"""
    count = progress["requirements"]
    if not count:
        return "no requirements yet"
    statuses = ", ".join(f"{number} {status}" for status, number in progress["requirements_by_status"].items())
    line = f"{count} requirement{'s' if count != 1 else ''} ({statuses})"
    if progress["tasks"] or progress["tasks_abandoned"]:
        line += f" | {progress['tasks_complete']}/{progress['tasks']} tasks complete"
        if progress["tasks_abandoned"]:
            line += f", {progress['tasks_abandoned']} abandoned"
    return line


def project_rollups(db: DatabaseManager) -> list[dict[str, Any]]:
    """Every project with its progress, in ID order, for the dashboard"""
    projects = db.get_records("projects", "id, title, status", order_by="project_number")
    return [{**dict(project), **project_progress(db, project["id"])} for project in projects]


class ProjectHandler(BaseHandler):
    """Handler for project MCP tools"""

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return project tool definitions"""
        return [
            {
                "name": "create_project",
                "description": (
                    "Create a project: a group of requirements (an epic, roadmap item, layer) and its purpose"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "purpose": {
                            "type": "string",
                            "description": "The goal its requirements serve; exported documents open with it",
                        },
                        "success_criteria": {"type": "array", "items": {"type": "string"}},
                        "out_of_scope": {"type": "array", "items": {"type": "string"}},
                        "requirement_ids": {"type": "array", "items": {"type": "string"}},
                        "author": {"type": "string"},
                    },
                    "required": ["title", "purpose"],
                },
            },
            {
                "name": "update_project",
                "description": "Edit a project, close it, or change which requirements belong to it",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "title": {"type": "string"},
                        "purpose": {"type": "string"},
                        "success_criteria": {"type": "array", "items": {"type": "string"}},
                        "out_of_scope": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string", "enum": list(PROJECT_STATUSES)},
                        "add_requirement_ids": {"type": "array", "items": {"type": "string"}},
                        "remove_requirement_ids": {"type": "array", "items": {"type": "string"}},
                        **EDIT_OPTION_PROPERTIES,
                    },
                    "required": ["project_id"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_project":
                return self._create_project(**arguments)
            elif tool_name == "update_project":
                return self._update_project(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    def _missing_requirements(self, requirement_ids: list[str]) -> list[str]:
        """Those of requirement_ids that name no requirement"""
        return [
            requirement_id
            for requirement_id in requirement_ids
            if not self.db.check_exists("requirements", "id = ?", [requirement_id])
        ]

    def _create_project(self, **params) -> list[TextContent]:
        """Create a project, with its first requirements when they are given"""
        error = self._validate_required_params(params, ["title", "purpose"])
        if error:
            return self._create_error_response(error)
        title, purpose = params["title"].strip(), params["purpose"].strip()
        if not title or not purpose:
            return self._create_error_response(
                "A project needs a title and a purpose: the purpose is what says why its requirements belong together"
            )
        requirement_ids = list(dict.fromkeys(params.get("requirement_ids") or []))
        missing = self._missing_requirements(requirement_ids)
        if missing:
            return self._create_error_response(f"No requirement {', '.join(missing)}; nothing was created")
        author = params.get("author") or "MCP User"

        try:
            # The number is read inside the transaction that uses it, and the links go in with the record.
            with self.db.transaction() as cur:
                number = cur.execute("SELECT COALESCE(MAX(project_number), 0) + 1 FROM projects").fetchone()[0]
                project_id = f"PROJ-{number:04d}"
                cur.execute(
                    "INSERT INTO projects (id, project_number, title, purpose, success_criteria, out_of_scope, author) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        project_id,
                        number,
                        title,
                        purpose,
                        self._safe_json_dumps(params.get("success_criteria", [])),
                        self._safe_json_dumps(params.get("out_of_scope", [])),
                        author,
                    ],
                )
                for requirement_id in requirement_ids:
                    self._link("requirement", requirement_id, "project", project_id, "part_of", cursor=cur)
                cur.execute(
                    "INSERT INTO lifecycle_events (entity_type, entity_id, event_type, actor) "
                    "VALUES ('project', ?, 'created', ?)",
                    [project_id, author],
                )
        except Exception as e:
            return self._create_error_response("Failed to create project", e)

        structured = {"id": project_id, "title": title, "status": "Active", "requirements": requirement_ids}
        count = len(requirement_ids)
        action_info = f"📁 {count} requirement{'s' if count != 1 else ''}" if count else ""
        return self._create_structured_response("SUCCESS", f"Project {project_id} created", structured, action_info)

    def _update_project(self, **params) -> list[TextContent]:
        """Edit a project's content or status, and add or remove requirements, in one revision"""
        error = self._validate_required_params(params, ["project_id"])
        if error:
            return self._create_error_response(error)
        project_id = params["project_id"]
        changes = {name: params[name] for name in PROJECT_EDITABLE if name in params}
        add = list(dict.fromkeys(params.get("add_requirement_ids") or []))
        remove = list(dict.fromkeys(params.get("remove_requirement_ids") or []))
        if not changes and not add and not remove:
            return self._create_error_response(
                f"Nothing to update: pass at least one of {', '.join(PROJECT_EDITABLE)}, "
                "add_requirement_ids, remove_requirement_ids"
            )
        for name in ("title", "purpose"):
            if name in changes and not str(changes[name]).strip():
                return self._create_error_response(f"A project's {name} can't be empty")
        both = [requirement_id for requirement_id in add if requirement_id in remove]
        if both:
            return self._create_error_response(f"Asked to both add and remove {', '.join(both)}")

        def change_members(cur: sqlite3.Cursor, before: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
            if not add and not remove:
                return {}
            current = sorted(row[0] for row in cur.execute(PROJECT_REQUIREMENT_IDS_SQL, [project_id]).fetchall())
            missing = [
                requirement_id
                for requirement_id in add
                if cur.execute("SELECT 1 FROM requirements WHERE id = ?", [requirement_id]).fetchone() is None
            ]
            if missing:
                raise EditRefused(f"No requirement {', '.join(missing)}; nothing was changed")
            strangers = [requirement_id for requirement_id in remove if requirement_id not in current]
            if strangers:
                raise EditRefused(f"Not in {project_id}: {', '.join(strangers)}; nothing was changed")
            for requirement_id in add:
                self._link("requirement", requirement_id, "project", project_id, "part_of", cursor=cur)
            for requirement_id in remove:
                cur.execute(
                    "DELETE FROM relationships WHERE source_type = 'requirement' AND source_id = ? "
                    "AND target_type = 'project' AND target_id = ? AND relationship_type = 'part_of'",
                    [requirement_id, project_id],
                )
            after = sorted((set(current) | set(add)) - set(remove))
            return {} if after == current else {"requirements": (json.dumps(current), json.dumps(after))}

        try:
            result = self._apply_edit(
                "projects",
                "project",
                project_id,
                changes,
                editable=PROJECT_EDITABLE,
                json_fields=PROJECT_JSON_FIELDS,
                actor=params.get("actor") or "MCP User",
                reason=(params.get("reason") or "").strip() or None,
                if_revision=params.get("if_revision"),
                relink=change_members,
            )
        except (LookupError, RevisionConflict, EditRefused) as e:
            return self._create_error_response(str(e))

        structured = {"id": project_id, "changed": result.changed, "revision": result.revision}
        return self._create_structured_response(
            "SUCCESS", f"Project {project_id} updated", structured, self._describe_edit(result)
        )

    def _delete_project(self, **params) -> list[TextContent]:
        """Delete a project that holds no requirements"""
        error = self._validate_required_params(params, ["project_id"])
        if error:
            return self._create_error_response(error)
        project_id = params["project_id"]
        try:
            with self.db.transaction() as cur:
                if cur.execute("SELECT 1 FROM projects WHERE id = ?", [project_id]).fetchone() is None:
                    raise LookupError(f"Project {project_id} not found")
                members = [row[0] for row in cur.execute(PROJECT_REQUIREMENT_IDS_SQL, [project_id]).fetchall()]
                if members:
                    raise DeleteRefused(
                        f"Project {project_id} still holds {len(members)} requirement(s) "
                        f"({', '.join(sorted(members))}). "
                        "Take them out with update_project remove_requirement_ids first, or set its status to Closed "
                        "to keep the grouping and its purpose."
                    )
                cur.execute("DELETE FROM relationships WHERE source_id = ? OR target_id = ?", [project_id, project_id])
                cur.execute("DELETE FROM projects WHERE id = ?", [project_id])
                cur.execute(
                    "INSERT INTO lifecycle_events (entity_type, entity_id, event_type, actor) "
                    "VALUES ('project', ?, 'deleted', 'MCP User')",
                    [project_id],
                )
        except (LookupError, DeleteRefused) as e:
            return self._create_error_response(str(e))
        return self._create_above_fold_response("SUCCESS", f"Project {project_id} deleted")

    def _get_project_details(self, **params) -> list[TextContent]:
        """A project's purpose, its requirements and how far they have got"""
        error = self._validate_required_params(params, ["project_id"])
        if error:
            return self._create_error_response(error)

        try:
            projects = self.db.get_records("projects", "*", "id = ?", [params["project_id"]])
            if not projects:
                return self._create_error_response("Project not found")
            project = projects[0]

            report = f"""# Project Details: {project["id"]}

## Basic Information
- **Title**: {project["title"]}
- **Status**: {project["status"]}
- **Author**: {project["author"]}
- **Created**: {project["created_at"]}
- **Updated**: {project["updated_at"]}
- **Revision**: {project["revision"]}

## Purpose
{project["purpose"]}
"""
            report += self._format_sections(project, PROJECT_LIST_SECTIONS, "\n### {title}\n{body}")

            requirements = project_requirements(self.db, project["id"])
            report += f"\n## Requirements ({len(requirements)})\n"
            if requirements:
                for req in requirements:
                    report += f"- {req['id']}: {req['title']} [{req['status']}] {req['priority']}"
                    if req["task_count"]:
                        report += f" - {req['tasks_completed']}/{req['task_count']} tasks"
                    report += "\n"
                report += f"\n**Progress**: {describe_progress(project_progress(self.db, project['id']))}\n"
            else:
                report += (
                    "None yet: add them with update_project add_requirement_ids, "
                    "or pass project_ids to create_requirement\n"
                )

            report += self._format_linked("Decisions", PROJECT_DECISIONS_SQL, project["id"])
            report += self._format_comments("project", project["id"])

            count = len(requirements)
            action_info = (
                f"📁 {project['title']} | {project['status']} | {count} requirement{'s' if count != 1 else ''}"
            )
            return self._create_above_fold_response("INFO", f"Project {project['id']} details", action_info, report)

        except Exception as e:
            return self._create_error_response("Failed to get project details", e)
