#!/usr/bin/env python3
"""
Export Handler for MCP Lifecycle Management Server
Handles export and diagram generation operations
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mcp.types import TextContent

from .architecture_handler import ARCHITECTURE_LIST_SECTIONS
from .base_handler import BaseHandler
from .requirement_handler import REQUIREMENT_LIST_SECTIONS
from .task_handler import TASK_LIST_SECTIONS

# Task-to-task dependency edges as (task_id depends on depends_on_task_id). "blocks" links point
# blocker -> blocked, every other dependency kind points dependent -> dependency.
TASK_DEPENDENCY_EDGES = """
    SELECT e.task_id, e.depends_on_task_id
    FROM (
        SELECT source_id AS task_id, target_id AS depends_on_task_id FROM relationships
        WHERE source_type = 'task' AND target_type = 'task' AND relationship_type IN ('depends', 'requires', 'informs')
        UNION
        SELECT target_id, source_id FROM relationships
        WHERE source_type = 'task' AND target_type = 'task' AND relationship_type = 'blocks'
    ) e
    JOIN tasks t1 ON e.task_id = t1.id
    JOIN tasks t2 ON e.depends_on_task_id = t2.id
"""


# Statuses left out of diagrams by default: finished history rather than the shape of the project (roadmap R13).
DIAGRAM_OMITTED_STATUSES = {"requirements": ("Deprecated",), "architecture": ("Deprecated",)}

# How much of a title a node label keeps before it is cut (roadmap R13).
LABEL_LENGTH = 60


@dataclass
class Diagram:
    """A rendered diagram, with what it drew and what it left out (roadmap R13)."""

    content: str
    drawn: dict[str, int] = field(default_factory=dict)
    omitted: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        """One line for the response: what was drawn, and what was not."""
        drawn = ", ".join(f"{count} {kind}" for kind, count in self.drawn.items() if count)
        line = f"📊 {drawn or 'nothing to draw'}"
        if self.omitted:
            left_out = ", ".join(f"{count} {kind}" for kind, count in self.omitted.items() if count)
            if left_out:
                line += f" | left out: {left_out}"
        return line


def mermaid_label(record_id: str, title: str) -> str:
    """A node label mermaid can parse: the ID, the title clipped to LABEL_LENGTH, and no raw quotes or brackets."""
    clipped = title if len(title) <= LABEL_LENGTH else title[: LABEL_LENGTH - 1] + "…"
    safe = clipped.replace('"', "#quot;").replace("[", "(").replace("]", ")")
    return f'{node_id(record_id)}["{record_id}<br/>{safe}"]'


def node_id(record_id: str) -> str:
    """Mermaid node identifiers cannot contain dashes."""
    return record_id.replace("-", "_")


class ExportHandler(BaseHandler):
    """Handler for export and diagram generation MCP tools"""

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return export tool definitions"""
        return [
            {
                "name": "export_project_documentation",
                "description": "Export requirements, tasks and ADRs as Markdown files",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_name": {"type": "string", "description": "Used in file names"},
                        "include_requirements": {"type": "boolean", "default": True},
                        "include_tasks": {"type": "boolean", "default": True},
                        "include_architecture": {"type": "boolean", "default": True},
                        "output_directory": {"type": "string"},
                    },
                },
            },
            {
                "name": "create_architectural_diagrams",
                "description": "Generate Mermaid diagrams of the project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "diagram_type": {
                            "type": "string",
                            "enum": [
                                "requirements",
                                "tasks",
                                "architecture",
                                "full_project",
                                "directory_structure",
                                "dependencies",
                            ],
                        },
                        "requirement_ids": {"type": "array", "items": {"type": "string"}},
                        "include_relationships": {"type": "boolean", "default": True},
                        "output_format": {
                            "type": "string",
                            "enum": ["mermaid", "markdown_with_mermaid"],
                            "default": "mermaid",
                        },
                        "output_path": {"type": "string", "default": "exports"},
                    },
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "export_project_documentation":
                return self._export_project_documentation(**arguments)
            elif tool_name == "create_architectural_diagrams":
                return self._create_architectural_diagrams(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    def _export_project_documentation(self, **params) -> list[TextContent]:
        """Export comprehensive project documentation in markdown format"""
        try:
            project_name = params.get("project_name", "project")
            output_dir = params.get("output_directory", ".")

            # Create output directory if needed
            os.makedirs(output_dir, exist_ok=True)

            exported_files = []

            if params.get("include_requirements", True):
                exported_files.extend(self._export_requirements(project_name, output_dir))

            if params.get("include_tasks", True):
                exported_files.extend(self._export_tasks(project_name, output_dir))

            if params.get("include_architecture", True):
                exported_files.extend(self._export_architecture(project_name, output_dir))

            if exported_files:
                # Create above-the-fold response for successful export
                key_info = f"Exported {len(exported_files)} files to {output_dir}"
                action_info = f"📄 {project_name} documentation"
                details = "\n".join(f"- {f}" for f in exported_files)
                return self._create_above_fold_response("SUCCESS", key_info, action_info, details)
            else:
                return self._create_above_fold_response(
                    "INFO", "No data found to export", "Check if requirements, tasks, or architecture exist"
                )

        except Exception as e:
            return self._create_error_response("Failed to export project documentation", e)

    def _export_requirements(self, project_name: str, output_dir: str) -> list[str]:
        """Export requirements to markdown file"""
        requirements = self.db.get_records("requirements", "*", order_by="type, requirement_number")

        if not requirements:
            return []

        filename = f"{project_name}-requirements.md"
        filepath = os.path.join(output_dir, filename)

        content = f"# {project_name} - Requirements Documentation\n\n"
        content += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # Group by type
        req_by_type = {}
        for req in requirements:
            req_type = req["type"]
            if req_type not in req_by_type:
                req_by_type[req_type] = []
            req_by_type[req_type].append(req)

        for req_type, reqs in req_by_type.items():
            content += f"## {req_type} Requirements\n\n"
            for req in reqs:
                content += f"### {req['id']}: {req['title']}\n\n"
                content += f"- **Status**: {req['status']}\n"
                content += f"- **Priority**: {req['priority']}\n"
                content += f"- **Risk Level**: {req['risk_level']}\n"
                content += f"- **Author**: {req['author']}\n"
                content += f"- **Created**: {req['created_at']}\n"
                content += f"- **Updated**: {req['updated_at']}\n\n"

                content += f"**Current State**: {req['current_state']}\n\n"
                content += f"**Desired State**: {req['desired_state']}\n\n"

                if req["business_value"]:
                    content += f"**Business Value**: {req['business_value']}\n\n"

                if req["functional_requirements"]:
                    func_reqs = self._safe_json_loads(req["functional_requirements"])
                    if func_reqs:
                        content += "**Functional Requirements**:\n"
                        for fr in func_reqs:
                            content += f"- {fr}\n"
                        content += "\n"

                if req["acceptance_criteria"]:
                    acc_criteria = self._safe_json_loads(req["acceptance_criteria"])
                    if acc_criteria:
                        content += "**Acceptance Criteria**:\n"
                        for ac in acc_criteria:
                            content += f"- {ac}\n"
                        content += "\n"

                content += self._format_sections(req, REQUIREMENT_LIST_SECTIONS, "**{title}**:\n{body}\n")

                content += "---\n\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return [filename]

    def _export_tasks(self, project_name: str, output_dir: str) -> list[str]:
        """Export tasks to markdown file"""
        tasks = self.db.get_records("tasks", "*", order_by="task_number, subtask_number")

        if not tasks:
            return []

        filename = f"{project_name}-tasks.md"
        filepath = os.path.join(output_dir, filename)

        content = f"# {project_name} - Tasks Documentation\n\n"
        content += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        # Group by status
        tasks_by_status = {}
        for task in tasks:
            status = task["status"]
            if status not in tasks_by_status:
                tasks_by_status[status] = []
            tasks_by_status[status].append(task)

        for status, task_list in tasks_by_status.items():
            content += f"## {status} Tasks\n\n"
            for task in task_list:
                content += f"### {task['id']}: {task['title']}\n\n"
                content += f"- **Status**: {task['status']}\n"
                content += f"- **Priority**: {task['priority']}\n"
                content += f"- **Effort**: {task['effort'] or 'Not specified'}\n"
                content += f"- **Assignee**: {task['assignee'] or 'Unassigned'}\n"
                content += f"- **Created**: {task['created_at']}\n"
                content += f"- **Updated**: {task['updated_at']}\n\n"

                if task["user_story"]:
                    content += f"**User Story**: {task['user_story']}\n\n"

                if task["acceptance_criteria"]:
                    acc_criteria = self._safe_json_loads(task["acceptance_criteria"])
                    if acc_criteria:
                        content += "**Acceptance Criteria**:\n"
                        for ac in acc_criteria:
                            content += f"- {ac}\n"
                        content += "\n"

                content += self._format_sections(task, TASK_LIST_SECTIONS, "**{title}**:\n{body}\n")

                # Get linked requirements
                linked_reqs = self.db.execute_query(
                    """
                    SELECT r.id, r.title FROM requirements r
                    JOIN relationships rel ON rel.source_id = r.id
                    WHERE rel.source_type = 'requirement' AND rel.target_type = 'task'
                      AND rel.target_id = ? AND rel.relationship_type = 'implements'
                """,
                    [task["id"]],
                    fetch_all=True,
                    row_factory=True,
                )

                if linked_reqs:
                    content += "**Linked Requirements**:\n"
                    for req in linked_reqs:
                        content += f"- {req['id']}: {req['title']}\n"
                    content += "\n"

                content += "---\n\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return [filename]

    def _export_architecture(self, project_name: str, output_dir: str) -> list[str]:
        """Export architecture decisions to markdown file"""
        architecture = self.db.get_records("architecture", "*", order_by="created_at DESC")

        if not architecture:
            return []

        filename = f"{project_name}-architecture.md"
        filepath = os.path.join(output_dir, filename)

        content = f"# {project_name} - Architecture Documentation\n\n"
        content += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        for arch in architecture:
            content += f"## {arch['id']}: {arch['title']}\n\n"
            content += f"- **Type**: {arch['type']}\n"
            content += f"- **Status**: {arch['status']}\n"
            content += f"- **Created**: {arch['created_at']}\n"
            content += f"- **Updated**: {arch['updated_at']}\n\n"

            if arch["authors"]:
                authors = self._safe_json_loads(arch["authors"])
                if authors:
                    content += f"- **Authors**: {', '.join(authors)}\n\n"

            deciders = self._safe_json_loads(arch["deciders"])
            if deciders:
                content += f"- **Deciders**: {', '.join(deciders)}\n\n"

            content += f"### Context\n{arch['context']}\n\n"
            content += f"### Decision\n{arch['decision_outcome']}\n\n"

            if arch["decision_drivers"]:
                drivers = self._safe_json_loads(arch["decision_drivers"])
                if drivers:
                    content += "### Decision Drivers\n"
                    for driver in drivers:
                        content += f"- {driver}\n"
                    content += "\n"

            if arch["considered_options"]:
                options = self._safe_json_loads(arch["considered_options"])
                if options:
                    content += "### Considered Options\n"
                    for option in options:
                        content += f"- {option}\n"
                    content += "\n"

            if arch["consequences"]:
                consequences = self._safe_json_loads(arch["consequences"])
                if consequences:
                    content += "### Consequences\n"
                    if isinstance(consequences, dict):
                        for key, value in consequences.items():
                            content += f"**{key.title()}**: {value}\n"
                    else:
                        content += f"{consequences}\n"
                    content += "\n"

            if arch["implementation_notes"]:
                content += f"### Implementation Notes\n{arch['implementation_notes']}\n\n"
            content += self._format_sections(arch, ARCHITECTURE_LIST_SECTIONS, "### {title}\n{body}\n")

            # Get linked requirements
            linked_reqs = self.db.execute_query(
                """
                SELECT r.id, r.title FROM requirements r
                JOIN relationships rel ON rel.source_id = r.id
                WHERE rel.source_type = 'requirement' AND rel.target_type = 'architecture'
                  AND rel.target_id = ? AND rel.relationship_type = 'addresses'
            """,
                [arch["id"]],
                fetch_all=True,
                row_factory=True,
            )

            if linked_reqs:
                content += "### Linked Requirements\n"
                for req in linked_reqs:
                    content += f"- {req['id']}: {req['title']}\n"
                content += "\n"

            content += "---\n\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return [filename]

    def _create_architectural_diagrams(self, **params) -> list[TextContent]:
        """Generate Mermaid diagrams for project architecture"""
        try:
            diagram_type = params.get("diagram_type", "full_project")
            include_relationships = params.get("include_relationships", True)
            output_format = params.get("output_format", "mermaid")
            output_path = params.get("output_path", "exports")

            # Validate diagram type
            valid_types = [
                "requirements",
                "tasks",
                "architecture",
                "full_project",
                "directory_structure",
                "dependencies",
            ]
            if diagram_type not in valid_types:
                return self._create_error_response(
                    f"Invalid diagram type: {diagram_type}. Valid types are: {', '.join(valid_types)}"
                )

            mermaid_content = ""
            diagram = None
            requirement_ids = params.get("requirement_ids", [])

            if diagram_type == "requirements":
                mermaid_content = self._generate_requirements_diagram(requirement_ids)
            elif diagram_type == "tasks":
                mermaid_content = self._generate_tasks_diagram(requirement_ids)
            elif diagram_type == "architecture":
                mermaid_content = self._generate_architecture_diagram(requirement_ids)
            elif diagram_type == "full_project":
                diagram = self._generate_full_project_diagram(include_relationships, requirement_ids)
                mermaid_content = diagram.content
            elif diagram_type == "directory_structure":
                mermaid_content = self._generate_directory_structure_diagram()
            elif diagram_type == "dependencies":
                mermaid_content = self._generate_dependencies_diagram(requirement_ids)

            if not mermaid_content:
                return self._create_above_fold_response(
                    "INFO", "No data found for diagram", f"Check if {diagram_type} data exists in the system"
                )

            # Prepare content for output
            if output_format == "markdown_with_mermaid":
                file_content = f"```mermaid\n{mermaid_content}\n```"
                result = file_content
            else:
                file_content = mermaid_content
                result = mermaid_content

            # Save to file if output_path is provided
            saved_file_path = None
            if output_path:
                # Validate output path
                if not self._validate_output_path(output_path):
                    return self._create_error_response("Invalid output path specified")

                # Ensure output directory exists
                if not self._ensure_output_directory(output_path):
                    return self._create_error_response(f"Cannot create output directory: {output_path}")

                # Generate filename and full path
                filename = self._generate_diagram_filename(diagram_type, output_format)
                full_path = os.path.join(output_path, filename)

                try:
                    # Write file
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(file_content)
                    saved_file_path = full_path
                except (OSError, PermissionError) as e:
                    return self._create_error_response(f"Failed to save diagram file: {str(e)}")

            # Create above-the-fold response
            key_info = f"{diagram_type.replace('_', ' ').title()} diagram generated"
            # What the diagram drew and left out, so nothing disappears silently (roadmap R13).
            action_info = diagram.summary() if diagram else f"📊 {output_format} format"
            if saved_file_path:
                action_info += f" | Saved to {saved_file_path}"

            return self._create_above_fold_response("SUCCESS", key_info, action_info, result)

        except Exception as e:
            return self._create_error_response("Failed to create architectural diagram", e)

    def _generate_requirements_diagram(self, requirement_ids: list[str] = None) -> str:
        """Generate requirements flowchart"""
        if requirement_ids:
            # Filter specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            requirements = self.db.execute_query(
                f"SELECT * FROM requirements WHERE id IN ({placeholders}) ORDER BY type, requirement_number",
                requirement_ids,
                fetch_all=True,
                row_factory=True,
            )
        else:
            requirements = self.db.get_records("requirements", "*", order_by="type, requirement_number")

        if not requirements:
            return ""

        mermaid_content = "flowchart TD\n"

        # Group by type
        req_by_type = {}
        for req in requirements:
            req_type = req["type"]
            if req_type not in req_by_type:
                req_by_type[req_type] = []
            req_by_type[req_type].append(req)

        # Add type nodes
        for req_type in req_by_type:
            mermaid_content += f"    {req_type}[{req_type} Requirements]\n"

        # Add requirement nodes
        for req_type, reqs in req_by_type.items():
            for req in reqs:
                node_id = req["id"].replace("-", "_")
                status_color = {
                    "Draft": "fill:#ff9999",
                    "Under Review": "fill:#ffcc99",
                    "Approved": "fill:#99ccff",
                    "Ready": "fill:#99ff99",
                    "Implemented": "fill:#ccffcc",
                    "Validated": "fill:#99ff99",
                    "Deprecated": "fill:#cccccc",
                }.get(req["status"], "fill:#ffffff")

                title_short = req["title"][:30] + "..." if len(req["title"]) > 30 else req["title"]
                mermaid_content += f'    {node_id}["{req["id"]}<br/>{title_short}"]\n'
                mermaid_content += f"    {req_type} --> {node_id}\n"
                mermaid_content += f"    style {node_id} {status_color}\n"

        return mermaid_content

    def _generate_tasks_diagram(self, requirement_ids: list[str] = None) -> str:
        """Generate task hierarchy diagram"""
        if requirement_ids:
            # Get tasks for specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            tasks = self.db.execute_query(
                f"""
                SELECT DISTINCT t.* FROM tasks t
                JOIN relationships rel ON rel.target_id = t.id
                WHERE rel.source_type = 'requirement' AND rel.target_type = 'task'
                  AND rel.relationship_type = 'implements' AND rel.source_id IN ({placeholders})
                ORDER BY t.task_number, t.subtask_number
            """,
                requirement_ids,
                fetch_all=True,
                row_factory=True,
            )
        else:
            tasks = self.db.get_records("tasks", "*", order_by="task_number, subtask_number")

        if not tasks:
            return ""

        mermaid_content = "flowchart TD\n"
        parent_of = {
            row["source_id"]: row["target_id"]
            for row in self.db.execute_query(
                """
                SELECT source_id, target_id FROM relationships
                WHERE source_type = 'task' AND target_type = 'task' AND relationship_type = 'parent'
            """,
                fetch_all=True,
                row_factory=True,
            )
        }

        # Add task nodes
        for task in tasks:
            node_id = task["id"].replace("-", "_")
            status_color = {
                "Not Started": "fill:#ff9999",
                "In Progress": "fill:#ffcc99",
                "Blocked": "fill:#ff6666",
                "Complete": "fill:#99ff99",
                "Abandoned": "fill:#cccccc",
            }.get(task["status"], "fill:#ffffff")

            title_short = task["title"][:30] + "..." if len(task["title"]) > 30 else task["title"]
            mermaid_content += f'    {node_id}["{task["id"]}<br/>{title_short}"]\n'
            mermaid_content += f"    style {node_id} {status_color}\n"

            # Add parent-child relationships
            if task["id"] in parent_of:
                parent_id = parent_of[task["id"]].replace("-", "_")
                mermaid_content += f"    {parent_id} --> {node_id}\n"

        return mermaid_content

    def _generate_architecture_diagram(self, requirement_ids: list[str] = None) -> str:
        """Generate architecture decisions diagram"""
        if requirement_ids:
            # Get architecture decisions for specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            architecture = self.db.execute_query(
                f"""
                SELECT DISTINCT a.* FROM architecture a
                JOIN relationships rel ON rel.target_id = a.id
                WHERE rel.source_type = 'requirement' AND rel.target_type = 'architecture'
                  AND rel.relationship_type = 'addresses' AND rel.source_id IN ({placeholders})
                ORDER BY a.created_at DESC
            """,
                requirement_ids,
                fetch_all=True,
                row_factory=True,
            )
        else:
            architecture = self.db.get_records("architecture", "*", order_by="created_at DESC")

        if not architecture:
            return ""

        mermaid_content = "flowchart TD\n"

        for arch in architecture:
            node_id = arch["id"].replace("-", "_")
            status_color = {
                "Proposed": "fill:#ffcc99",
                "Accepted": "fill:#99ff99",
                "Rejected": "fill:#ff9999",
                "Deprecated": "fill:#cccccc",
                "Superseded": "fill:#cccccc",
            }.get(arch["status"], "fill:#ffffff")

            title_short = arch["title"][:30] + "..." if len(arch["title"]) > 30 else arch["title"]
            mermaid_content += f'    {node_id}["{arch["id"]}<br/>{title_short}"]\n'
            mermaid_content += f"    style {node_id} {status_color}\n"

        return mermaid_content

    def _generate_full_project_diagram(self, include_relationships: bool, requirement_ids: list[str] = None) -> Diagram:
        """The project graph: every non-deprecated record, with the links between them (roadmap R13).

        Nothing is capped: the old version kept the first 10 requirements, 10 tasks and 5 decisions and drew at most
        20 edges, all silently. Edges come from relationships and are kept only when both ends are drawn.
        """
        requirements, requirements_left_out = self._diagram_requirements(requirement_ids)
        tasks = self._diagram_tasks(requirement_ids)
        decisions, decisions_left_out = self._diagram_decisions(requirement_ids)
        if not (requirements or tasks or decisions):
            return Diagram("")

        lines = ["flowchart TD"]
        for record in (*requirements, *tasks, *decisions):
            lines.append(f"    {mermaid_label(record['id'], record['title'])}")

        if include_relationships:
            drawn = {record["id"] for record in (*requirements, *tasks, *decisions)}
            edges = [
                ("requirement", "task", "implements", "implements"),
                ("requirement", "architecture", "addresses", "addresses"),
                ("task", "architecture", "implements", "implements"),
                ("architecture", "architecture", "supersedes", "supersedes"),
            ]
            for source_type, target_type, link, label in edges:
                for source, target in self._diagram_links(source_type, target_type, link):
                    if source in drawn and target in drawn:
                        lines.append(f"    {node_id(source)} -->|{label}| {node_id(target)}")

        counts = {"requirements": len(requirements), "tasks": len(tasks), "decisions": len(decisions)}
        left_out = {"deprecated requirements": requirements_left_out, "deprecated decisions": decisions_left_out}
        return Diagram("\n".join(lines) + "\n", counts, {kind: n for kind, n in left_out.items() if n})

    def _diagram_requirements(self, requirement_ids: list[str] = None) -> tuple[list[Any], int]:
        """Requirements to draw, and how many deprecated ones were left out (roadmap R13)"""
        records = self.db.get_records("requirements", "*", order_by="type, requirement_number")
        if requirement_ids:
            records = [record for record in records if record["id"] in set(requirement_ids)]
        kept = [record for record in records if record["status"] not in DIAGRAM_OMITTED_STATUSES["requirements"]]
        return kept, len(records) - len(kept)

    def _diagram_tasks(self, requirement_ids: list[str] = None) -> list[Any]:
        """Tasks to draw: every task, or those implementing the requirements asked for"""
        if not requirement_ids:
            return self.db.get_records("tasks", "*", order_by="task_number, subtask_number")
        placeholders = ",".join(["?"] * len(requirement_ids))
        return (
            self.db.execute_query(
                f"""
                SELECT DISTINCT t.* FROM tasks t
                JOIN relationships rel ON rel.target_id = t.id
                WHERE rel.source_type = 'requirement' AND rel.target_type = 'task'
                  AND rel.relationship_type = 'implements' AND rel.source_id IN ({placeholders})
                ORDER BY t.task_number, t.subtask_number
                """,
                requirement_ids,
                fetch_all=True,
                row_factory=True,
            )
            or []
        )

    def _diagram_decisions(self, requirement_ids: list[str] = None) -> tuple[list[Any], int]:
        """Decisions to draw, and how many deprecated ones were left out (roadmap R13)"""
        if requirement_ids:
            placeholders = ",".join(["?"] * len(requirement_ids))
            records = (
                self.db.execute_query(
                    f"""
                    SELECT DISTINCT a.* FROM architecture a
                    JOIN relationships rel ON rel.target_id = a.id
                    WHERE rel.source_type = 'requirement' AND rel.target_type = 'architecture'
                      AND rel.relationship_type = 'addresses' AND rel.source_id IN ({placeholders})
                    ORDER BY a.created_at DESC
                    """,
                    requirement_ids,
                    fetch_all=True,
                    row_factory=True,
                )
                or []
            )
        else:
            records = self.db.get_records("architecture", "*", order_by="created_at DESC")
        kept = [record for record in records if record["status"] not in DIAGRAM_OMITTED_STATUSES["architecture"]]
        return kept, len(records) - len(kept)

    def _diagram_links(self, source_type: str, target_type: str, relationship_type: str) -> list[tuple[str, str]]:
        """Every link of one kind, as (source_id, target_id)"""
        rows = self.db.execute_query(
            "SELECT source_id, target_id FROM relationships "
            "WHERE source_type = ? AND target_type = ? AND relationship_type = ? ORDER BY source_id, target_id",
            [source_type, target_type, relationship_type],
            fetch_all=True,
            row_factory=True,
        )
        return [(row["source_id"], row["target_id"]) for row in rows or []]

    def _generate_directory_structure_diagram(self) -> str:
        """Generate directory structure diagram"""
        return """flowchart TD
    Root[Project Root]
    Src[src/]
    Docs[docs/]
    Tests[tests/]
    Root --> Src
    Root --> Docs
    Root --> Tests"""

    def _generate_dependencies_diagram(self, requirement_ids: list[str] = None) -> str:
        """Generate dependencies diagram"""
        if requirement_ids:
            # Get task dependencies for specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            task_ids_query = self.db.execute_query(
                f"""
                SELECT DISTINCT target_id AS task_id FROM relationships
                WHERE source_type = 'requirement' AND target_type = 'task'
                  AND relationship_type = 'implements' AND source_id IN ({placeholders})
            """,
                requirement_ids,
                fetch_all=True,
                row_factory=True,
            )

            task_ids = [row["task_id"] for row in task_ids_query]
            if task_ids:
                task_placeholders = ",".join(["?"] * len(task_ids))
                dependencies = self.db.execute_query(
                    f"""
                    {TASK_DEPENDENCY_EDGES}
                    WHERE e.task_id IN ({task_placeholders})
                       OR e.depends_on_task_id IN ({task_placeholders})
                """,
                    task_ids + task_ids,
                    fetch_all=True,
                    row_factory=True,
                )
            else:
                dependencies = []
        else:
            dependencies = self.db.execute_query(TASK_DEPENDENCY_EDGES, fetch_all=True, row_factory=True)

        if not dependencies:
            return "flowchart TD\n    NoDeps[No task dependencies found]\n"

        mermaid_content = "flowchart TD\n"

        for dep in dependencies:
            task_id = dep["task_id"].replace("-", "_")
            depends_on = dep["depends_on_task_id"].replace("-", "_")
            mermaid_content += f"    {depends_on} --> {task_id}\n"

        return mermaid_content

    def _get_diagram_file_extension(self, output_format: str) -> str:
        """Get appropriate file extension based on output format"""
        if output_format == "markdown_with_mermaid":
            return ".md"
        else:  # mermaid format
            return ".mmd"

    def _generate_diagram_filename(self, diagram_type: str, output_format: str) -> str:
        """Generate structured filename for diagram files"""
        # Clean diagram_type for safe filename
        safe_diagram_type = diagram_type.replace("_", "-").lower()

        # Generate timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")

        # Get file extension
        extension = self._get_diagram_file_extension(output_format)

        return f"{safe_diagram_type}-diagram-{timestamp}{extension}"

    def _validate_output_path(self, output_path: str) -> bool:
        """Validate output path for security (prevent path traversal)"""
        if not output_path:
            return False

        # Check for path traversal attempts
        if ".." in output_path:
            return False

        # Additional safety checks could be added here
        return True

    def _ensure_output_directory(self, output_path: str) -> bool:
        """Create output directory if it doesn't exist"""
        try:
            os.makedirs(output_path, exist_ok=True)
            return True
        except (OSError, PermissionError):
            return False
