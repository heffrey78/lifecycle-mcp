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

from .architecture_handler import ARCHITECTURE_LIST_SECTIONS, amendments, format_amendments
from .base_handler import BaseHandler
from .requirement_handler import REQUIREMENT_LIST_SECTIONS
from .task_handler import TASK_LIST_SECTIONS

# Statuses left out of diagrams by default: finished history rather than the shape of the project (roadmap R13).
DIAGRAM_OMITTED_STATUSES = {"requirements": ("Deprecated",), "architecture": ("Deprecated",)}

# How much of a title a node label keeps before it is cut (roadmap R13).
LABEL_LENGTH = 60

# Node fills by status, shared by every diagram (roadmap R13).
DEFAULT_COLOR = "fill:#ffffff"
REQUIREMENT_STATUS_COLORS = {
    "Draft": "fill:#ff9999",
    "Under Review": "fill:#ffcc99",
    "Approved": "fill:#99ccff",
    "Architecture": "fill:#99ccff",
    "Ready": "fill:#99ff99",
    "Implemented": "fill:#ccffcc",
    "Validated": "fill:#99ff99",
    "Deprecated": "fill:#cccccc",
}
TASK_STATUS_COLORS = {
    "Not Started": "fill:#ff9999",
    "In Progress": "fill:#ffcc99",
    "Blocked": "fill:#ff6666",
    "Complete": "fill:#99ff99",
    "Abandoned": "fill:#cccccc",
}
ARCHITECTURE_STATUS_COLORS = {
    "Proposed": "fill:#ffcc99",
    "Accepted": "fill:#99ff99",
    "Rejected": "fill:#ff9999",
    "Deprecated": "fill:#cccccc",
    "Superseded": "fill:#cccccc",
}


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
                            "enum": ["requirements", "tasks", "architecture", "full_project", "dependencies"],
                        },
                        "requirement_ids": {"type": "array", "items": {"type": "string"}},
                        "include_relationships": {"type": "boolean", "default": True},
                        "limit": {"type": "integer", "description": "Cap each kind of record; the rest are reported"},
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
                if req["origin"] != "stated":
                    content += f"- **Origin**: {req['origin']}\n"
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

                content += self._exported_comments("requirement", req["id"])
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
                content += f"- **Updated**: {task['updated_at']}\n"
                # The commit and evidence behind the task's status travel with it (roadmap R12).
                if task["commit_ref"]:
                    content += f"- **Commit**: {task['commit_ref']}\n"
                if task["evidence"]:
                    content += f"- **Evidence**: {task['evidence']}\n"
                content += "\n"

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

                content += self._exported_comments("task", task["id"])
                content += "---\n\n"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return [filename]

    def _exported_comments(self, entity_type: str, entity_id: str) -> str:
        """A record's comments for the exported documentation, oldest first; "" when it has none (roadmap R12).

        Comments were the only home evidence had, and export left them out entirely (F-26, F-31).
        """
        rows = (
            self.db.execute_query(
                "SELECT reviewer, comment, created_at FROM reviews WHERE entity_type = ? AND entity_id = ? "
                "ORDER BY created_at, id",
                [entity_type, entity_id],
                fetch_all=True,
                row_factory=True,
            )
            or []
        )
        if not rows:
            return ""
        lines = "".join(f"- **{row['reviewer']}** ({row['created_at']}): {row['comment']}\n" for row in rows)
        return f"**Comments**:\n{lines}\n"

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
            # A hand-off document has to carry the correction with the decision, not leave it in the comments (R20)
            amended = format_amendments(amendments(self.db, arch["id"]), heading="### Amendments")
            content += f"{amended}\n" if amended else ""

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

            consequences = self._format_consequences(arch["consequences"], "### Consequences")
            if consequences:
                content += consequences + "\n"

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

            content += self._exported_comments("architecture", arch["id"])
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
            valid_types = ["requirements", "tasks", "architecture", "full_project", "dependencies"]
            if diagram_type not in valid_types:
                return self._create_error_response(
                    f"Invalid diagram type: {diagram_type}. Valid types are: {', '.join(valid_types)}"
                )

            mermaid_content = ""
            requirement_ids = params.get("requirement_ids", [])
            limit = params.get("limit")

            if diagram_type == "requirements":
                diagram = self._generate_requirements_diagram(requirement_ids, limit)
            elif diagram_type == "tasks":
                diagram = self._generate_tasks_diagram(requirement_ids, limit)
            elif diagram_type == "architecture":
                diagram = self._generate_architecture_diagram(requirement_ids, limit)
            elif diagram_type == "full_project":
                diagram = self._generate_full_project_diagram(include_relationships, requirement_ids, limit)
            else:
                diagram = self._generate_dependencies_diagram(requirement_ids, limit)
            mermaid_content = diagram.content

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
            action_info = diagram.summary()
            if saved_file_path:
                action_info += f" | Saved to {saved_file_path}"

            return self._create_above_fold_response("SUCCESS", key_info, action_info, result)

        except Exception as e:
            return self._create_error_response("Failed to create architectural diagram", e)

    def _generate_requirements_diagram(self, requirement_ids: list[str] = None, limit: int | None = None) -> Diagram:
        """Requirements grouped by type, with the links between them (roadmap R13)"""
        requirements, left_out = self._diagram_requirements(requirement_ids)
        requirements, over_limit = self._capped(requirements, limit)
        if not requirements:
            return Diagram("")

        by_type: dict[str, list[Any]] = {}
        for record in requirements:
            by_type.setdefault(record["type"], []).append(record)

        lines = ["flowchart TD"]
        for req_type in by_type:
            lines.append(f"    {req_type}[{req_type} Requirements]")
        for req_type, records in by_type.items():
            for record in records:
                name = node_id(record["id"])
                lines.append(f"    {mermaid_label(record['id'], record['title'])}")
                lines.append(f"    {req_type} --> {name}")
                lines.append(f"    style {name} {REQUIREMENT_STATUS_COLORS.get(record['status'], DEFAULT_COLOR)}")

        drawn = {record["id"] for record in requirements}
        for link, label in (("parent", "parent of"), ("depends", "depends on")):
            for source, target in self._diagram_links("requirement", "requirement", link):
                if source in drawn and target in drawn:
                    # parent links point child -> parent, so the parent is drawn above the child
                    edge = (target, source) if link == "parent" else (source, target)
                    lines.append(f"    {node_id(edge[0])} -->|{label}| {node_id(edge[1])}")

        omitted = self._omitted(deprecated_requirements=left_out, requirements_over_the_limit=over_limit)
        return Diagram("\n".join(lines) + "\n", {"requirements": len(requirements)}, omitted)

    def _generate_tasks_diagram(self, requirement_ids: list[str] = None, limit: int | None = None) -> Diagram:
        """Tasks with their subtasks and the tasks they wait on (roadmap R13)"""
        tasks, over_limit = self._capped(self._diagram_tasks(requirement_ids), limit)
        if not tasks:
            return Diagram("")

        lines = ["flowchart TD"]
        for task in tasks:
            name = node_id(task["id"])
            lines.append(f"    {mermaid_label(task['id'], task['title'])}")
            lines.append(f"    style {name} {TASK_STATUS_COLORS.get(task['status'], DEFAULT_COLOR)}")

        drawn = {task["id"] for task in tasks}
        links = (("parent", "subtask of"), ("depends", "depends on"), ("requires", "requires"), ("blocks", "blocks"))
        for link, label in links:
            for source, target in self._diagram_links("task", "task", link):
                if source in drawn and target in drawn:
                    lines.append(f"    {node_id(source)} -->|{label}| {node_id(target)}")

        omitted = self._omitted(tasks_over_the_limit=over_limit)
        return Diagram("\n".join(lines) + "\n", {"tasks": len(tasks)}, omitted)

    def _generate_architecture_diagram(self, requirement_ids: list[str] = None, limit: int | None = None) -> Diagram:
        """Decisions, what they supersede, and the requirements they address (roadmap R13)"""
        decisions, left_out = self._diagram_decisions(requirement_ids)
        decisions, over_limit = self._capped(decisions, limit)
        if not decisions:
            return Diagram("")

        lines = ["flowchart TD"]
        for decision in decisions:
            name = node_id(decision["id"])
            lines.append(f"    {mermaid_label(decision['id'], decision['title'])}")
            lines.append(f"    style {name} {ARCHITECTURE_STATUS_COLORS.get(decision['status'], DEFAULT_COLOR)}")

        drawn = {decision["id"] for decision in decisions}
        for source, target in self._diagram_links("architecture", "architecture", "supersedes"):
            if source in drawn and target in drawn:
                lines.append(f"    {node_id(source)} -->|supersedes| {node_id(target)}")

        # The requirements these decisions serve, so a decision is not a box on its own.
        requirements, _ = self._diagram_requirements(requirement_ids)
        titles = {record["id"]: record["title"] for record in requirements}
        addressed = [
            (source, target)
            for source, target in self._diagram_links("requirement", "architecture", "addresses")
            if target in drawn and source in titles
        ]
        for record_id in dict.fromkeys(source for source, _ in addressed):
            lines.append(f"    {mermaid_label(record_id, titles[record_id])}")
        for source, target in addressed:
            lines.append(f"    {node_id(source)} -->|addresses| {node_id(target)}")

        counts = {"decisions": len(decisions), "requirements": len({source for source, _ in addressed})}
        omitted = self._omitted(deprecated_decisions=left_out, decisions_over_the_limit=over_limit)
        return Diagram("\n".join(lines) + "\n", counts, omitted)

    def _generate_full_project_diagram(
        self, include_relationships: bool, requirement_ids: list[str] = None, limit: int | None = None
    ) -> Diagram:
        """The project graph: every non-deprecated record, with the links between them (roadmap R13).

        Nothing is capped: the old version kept the first 10 requirements, 10 tasks and 5 decisions and drew at most
        20 edges, all silently. Edges come from relationships and are kept only when both ends are drawn.
        """
        requirements, requirements_left_out = self._diagram_requirements(requirement_ids)
        requirements, requirements_over = self._capped(requirements, limit)
        tasks, tasks_over = self._capped(self._diagram_tasks(requirement_ids), limit)
        decisions, decisions_left_out = self._diagram_decisions(requirement_ids)
        decisions, decisions_over = self._capped(decisions, limit)
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
        omitted = self._omitted(
            deprecated_requirements=requirements_left_out,
            deprecated_decisions=decisions_left_out,
            requirements_over_the_limit=requirements_over,
            tasks_over_the_limit=tasks_over,
            decisions_over_the_limit=decisions_over,
        )
        return Diagram("\n".join(lines) + "\n", counts, omitted)

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

    @staticmethod
    def _omitted(**counts: int) -> dict[str, int]:
        """What a Diagram left out, without the zeroes: keyword names become the words in the response"""
        return {kind.replace("_", " "): count for kind, count in counts.items() if count}

    @staticmethod
    def _capped(records: list[Any], limit: int | None) -> tuple[list[Any], int]:
        """The records to draw and how many the limit cut; without a limit nothing is cut (roadmap R13)"""
        if limit is None or limit < 0 or len(records) <= limit:
            return records, 0
        return records[:limit], len(records) - limit

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

    def _generate_dependencies_diagram(self, requirement_ids: list[str] = None, limit: int | None = None) -> Diagram:
        """The tasks that wait on other tasks, with titles rather than bare IDs (roadmap R13)"""
        tasks = {task["id"]: task for task in self._diagram_tasks(requirement_ids)}
        edges = []
        for link, label in (("depends", "depends on"), ("requires", "requires"), ("informs", "informs")):
            edges += [(source, target, label) for source, target in self._diagram_links("task", "task", link)]
        edges += [(source, target, "blocks") for source, target in self._diagram_links("task", "task", "blocks")]
        edges = [edge for edge in edges if edge[0] in tasks and edge[1] in tasks]
        edges, over_limit = self._capped(edges, limit)

        if not edges:
            return Diagram("flowchart TD\n    NoDeps[No task dependencies found]\n")

        lines = ["flowchart TD"]
        drawn = dict.fromkeys([edge[0] for edge in edges] + [edge[1] for edge in edges])
        for record_id in drawn:
            task = tasks[record_id]
            lines.append(f"    {mermaid_label(record_id, task['title'])}")
            lines.append(f"    style {node_id(record_id)} {TASK_STATUS_COLORS.get(task['status'], DEFAULT_COLOR)}")
        for source, target, label in edges:
            lines.append(f"    {node_id(source)} -->|{label}| {node_id(target)}")

        omitted = self._omitted(dependencies_over_the_limit=over_limit)
        return Diagram("\n".join(lines) + "\n", {"tasks": len(drawn), "dependencies": len(edges)}, omitted)

    def _get_diagram_file_extension(self, output_format: str) -> str:
        """Get appropriate file extension based on output format"""
        if output_format == "markdown_with_mermaid":
            return ".md"
        else:  # mermaid format
            return ".mmd"

    def _generate_diagram_filename(self, diagram_type: str, output_format: str) -> str:
        """One file per diagram type, overwritten on each render, so they stop piling up (roadmap R13, F-17)"""
        return f"{diagram_type}-diagram{self._get_diagram_file_extension(output_format)}"

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
