#!/usr/bin/env python3
"""
Export Handler for MCP Lifecycle Management Server
Handles export and diagram generation operations
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any
from mcp.types import TextContent

from .base_handler import BaseHandler


class ExportHandler(BaseHandler):
    """Handler for export and diagram generation MCP tools"""
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return export tool definitions"""
        return [
            {
                "name": "export_project_documentation",
                "description": "Export comprehensive project documentation in markdown format",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_name": {"type": "string", "description": "Name for the project to use in filenames"},
                        "include_requirements": {"type": "boolean", "default": True},
                        "include_tasks": {"type": "boolean", "default": True},
                        "include_architecture": {"type": "boolean", "default": True},
                        "output_directory": {"type": "string", "description": "Directory to save the exported files"}
                    }
                }
            },
            {
                "name": "create_architectural_diagrams",
                "description": "Generate Mermaid diagrams for project architecture and relationships",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "diagram_type": {"type": "string", "enum": ["requirements", "tasks", "architecture", "full_project", "directory_structure", "dependencies"]},
                        "requirement_ids": {"type": "array", "items": {"type": "string"}, "description": "Specific requirements to include"},
                        "include_relationships": {"type": "boolean", "default": True},
                        "output_format": {"type": "string", "enum": ["mermaid", "markdown_with_mermaid"], "default": "mermaid"},
                        "interactive": {"type": "boolean", "default": False, "description": "Start interactive conversation for complex diagrams"},
                        "output_path": {"type": "string", "default": "exports", "description": "Directory path to save diagram files (defaults to 'exports')"}
                    }
                }
            }
        ]
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
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
    
    def _export_project_documentation(self, **params) -> List[TextContent]:
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
                return self._create_above_fold_response("INFO", "No data found to export", "Check if requirements, tasks, or architecture exist")
                
        except Exception as e:
            return self._create_error_response("Failed to export project documentation", e)
    
    def _export_requirements(self, project_name: str, output_dir: str) -> List[str]:
        """Export requirements to markdown file"""
        requirements = self.db.get_records(
            "requirements",
            "*",
            order_by="type, requirement_number"
        )
        
        if not requirements:
            return []
        
        filename = f"{project_name}-requirements.md"
        filepath = os.path.join(output_dir, filename)
        
        content = f"# {project_name} - Requirements Documentation\n\n"
        content += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # Group by type
        req_by_type = {}
        for req in requirements:
            req_type = req['type']
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
                
                if req['business_value']:
                    content += f"**Business Value**: {req['business_value']}\n\n"
                
                if req['functional_requirements']:
                    func_reqs = self._safe_json_loads(req['functional_requirements'])
                    if func_reqs:
                        content += "**Functional Requirements**:\n"
                        for fr in func_reqs:
                            content += f"- {fr}\n"
                        content += "\n"
                
                if req['acceptance_criteria']:
                    acc_criteria = self._safe_json_loads(req['acceptance_criteria'])
                    if acc_criteria:
                        content += "**Acceptance Criteria**:\n"
                        for ac in acc_criteria:
                            content += f"- {ac}\n"
                        content += "\n"
                
                content += "---\n\n"
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        return [filename]
    
    def _export_tasks(self, project_name: str, output_dir: str) -> List[str]:
        """Export tasks to markdown file"""
        tasks = self.db.get_records(
            "tasks",
            "*",
            order_by="task_number, subtask_number"
        )
        
        if not tasks:
            return []
        
        filename = f"{project_name}-tasks.md"
        filepath = os.path.join(output_dir, filename)
        
        content = f"# {project_name} - Tasks Documentation\n\n"
        content += f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        # Group by status
        tasks_by_status = {}
        for task in tasks:
            status = task['status']
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
                
                if task['user_story']:
                    content += f"**User Story**: {task['user_story']}\n\n"
                
                if task['acceptance_criteria']:
                    acc_criteria = self._safe_json_loads(task['acceptance_criteria'])
                    if acc_criteria:
                        content += "**Acceptance Criteria**:\n"
                        for ac in acc_criteria:
                            content += f"- {ac}\n"
                        content += "\n"
                
                # Get linked requirements
                linked_reqs = self.db.execute_query("""
                    SELECT r.id, r.title FROM requirements r
                    JOIN requirement_tasks rt ON r.id = rt.requirement_id
                    WHERE rt.task_id = ?
                """, [task['id']], fetch_all=True, row_factory=True)
                
                if linked_reqs:
                    content += "**Linked Requirements**:\n"
                    for req in linked_reqs:
                        content += f"- {req['id']}: {req['title']}\n"
                    content += "\n"
                
                content += "---\n\n"
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        return [filename]
    
    def _export_architecture(self, project_name: str, output_dir: str) -> List[str]:
        """Export architecture decisions to markdown file"""
        architecture = self.db.get_records(
            "architecture",
            "*",
            order_by="created_at DESC"
        )
        
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
            
            if arch['authors']:
                authors = self._safe_json_loads(arch['authors'])
                if authors:
                    content += f"- **Authors**: {', '.join(authors)}\n\n"
            
            content += f"### Context\n{arch['context']}\n\n"
            content += f"### Decision\n{arch['decision_outcome']}\n\n"
            
            if arch['decision_drivers']:
                drivers = self._safe_json_loads(arch['decision_drivers'])
                if drivers:
                    content += "### Decision Drivers\n"
                    for driver in drivers:
                        content += f"- {driver}\n"
                    content += "\n"
            
            if arch['considered_options']:
                options = self._safe_json_loads(arch['considered_options'])
                if options:
                    content += "### Considered Options\n"
                    for option in options:
                        content += f"- {option}\n"
                    content += "\n"
            
            if arch['consequences']:
                consequences = self._safe_json_loads(arch['consequences'])
                if consequences:
                    content += "### Consequences\n"
                    if isinstance(consequences, dict):
                        for key, value in consequences.items():
                            content += f"**{key.title()}**: {value}\n"
                    else:
                        content += f"{consequences}\n"
                    content += "\n"
            
            # Get linked requirements
            linked_reqs = self.db.execute_query("""
                SELECT r.id, r.title FROM requirements r
                JOIN requirement_architecture ra ON r.id = ra.requirement_id
                WHERE ra.architecture_id = ?
            """, [arch['id']], fetch_all=True, row_factory=True)
            
            if linked_reqs:
                content += "### Linked Requirements\n"
                for req in linked_reqs:
                    content += f"- {req['id']}: {req['title']}\n"
                content += "\n"
            
            content += "---\n\n"
        
        with open(filepath, 'w') as f:
            f.write(content)
        
        return [filename]
    
    def _create_architectural_diagrams(self, **params) -> List[TextContent]:
        """Generate Mermaid diagrams for project architecture"""
        # Check if interactive mode is requested
        if params.get("interactive", False):
            # For interactive mode, we'd need to integrate with InterviewHandler
            # For now, provide a helpful message
            return self._create_above_fold_response(
                "INFO", 
                "Interactive mode requires architectural conversation",
                "Use start_architectural_conversation tool first"
            )
        
        try:
            diagram_type = params.get("diagram_type", "full_project")
            include_relationships = params.get("include_relationships", True)
            output_format = params.get("output_format", "mermaid")
            output_path = params.get("output_path", "exports")
            
            # Validate diagram type
            valid_types = ["requirements", "tasks", "architecture", "full_project", "directory_structure", "dependencies"]
            if diagram_type not in valid_types:
                return self._create_error_response(f"Invalid diagram type: {diagram_type}. Valid types are: {', '.join(valid_types)}")
            
            mermaid_content = ""
            requirement_ids = params.get("requirement_ids", [])
            
            if diagram_type == "requirements":
                mermaid_content = self._generate_requirements_diagram(requirement_ids)
            elif diagram_type == "tasks":
                mermaid_content = self._generate_tasks_diagram(requirement_ids)
            elif diagram_type == "architecture":
                mermaid_content = self._generate_architecture_diagram(requirement_ids)
            elif diagram_type == "full_project":
                mermaid_content = self._generate_full_project_diagram(include_relationships, requirement_ids)
            elif diagram_type == "directory_structure":
                mermaid_content = self._generate_directory_structure_diagram()
            elif diagram_type == "dependencies":
                mermaid_content = self._generate_dependencies_diagram(requirement_ids)
            
            if not mermaid_content:
                return self._create_above_fold_response("INFO", "No data found for diagram", f"Check if {diagram_type} data exists in the system")
            
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
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(file_content)
                    saved_file_path = full_path
                except (OSError, PermissionError) as e:
                    return self._create_error_response(f"Failed to save diagram file: {str(e)}")
            
            # Create above-the-fold response
            key_info = f"{diagram_type.replace('_', ' ').title()} diagram generated"
            action_info = f"📊 {output_format} format"
            if saved_file_path:
                action_info += f" | Saved to {saved_file_path}"
            
            return self._create_above_fold_response("SUCCESS", key_info, action_info, result)
            
        except Exception as e:
            return self._create_error_response("Failed to create architectural diagram", e)
    
    def _generate_requirements_diagram(self, requirement_ids: List[str] = None) -> str:
        """Generate requirements flowchart"""
        if requirement_ids:
            # Filter specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            requirements = self.db.execute_query(
                f"SELECT * FROM requirements WHERE id IN ({placeholders}) ORDER BY type, requirement_number",
                requirement_ids,
                fetch_all=True,
                row_factory=True
            )
        else:
            requirements = self.db.get_records(
                "requirements",
                "*",
                order_by="type, requirement_number"
        )
        
        if not requirements:
            return ""
        
        mermaid_content = "flowchart TD\n"
        
        # Group by type
        req_by_type = {}
        for req in requirements:
            req_type = req['type']
            if req_type not in req_by_type:
                req_by_type[req_type] = []
            req_by_type[req_type].append(req)
        
        # Add type nodes
        for req_type in req_by_type.keys():
            mermaid_content += f"    {req_type}[{req_type} Requirements]\n"
        
        # Add requirement nodes
        for req_type, reqs in req_by_type.items():
            for req in reqs:
                node_id = req['id'].replace('-', '_')
                status_color = {
                    'Draft': 'fill:#ff9999',
                    'Under Review': 'fill:#ffcc99',
                    'Approved': 'fill:#99ccff',
                    'Ready': 'fill:#99ff99',
                    'Implemented': 'fill:#ccffcc',
                    'Validated': 'fill:#99ff99',
                    'Deprecated': 'fill:#cccccc'
                }.get(req['status'], 'fill:#ffffff')
                
                title_short = req['title'][:30] + "..." if len(req['title']) > 30 else req['title']
                mermaid_content += f"    {node_id}[\"{req['id']}<br/>{title_short}\"]\n"
                mermaid_content += f"    {req_type} --> {node_id}\n"
                mermaid_content += f"    style {node_id} {status_color}\n"
        
        return mermaid_content
    
    def _generate_tasks_diagram(self, requirement_ids: List[str] = None) -> str:
        """Generate task hierarchy diagram"""
        if requirement_ids:
            # Get tasks for specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            tasks = self.db.execute_query(f"""
                SELECT DISTINCT t.* FROM tasks t
                JOIN requirement_tasks rt ON t.id = rt.task_id
                WHERE rt.requirement_id IN ({placeholders})
                ORDER BY t.task_number, t.subtask_number
            """, requirement_ids, fetch_all=True, row_factory=True)
        else:
            tasks = self.db.get_records(
                "tasks",
                "*",
                order_by="task_number, subtask_number"
            )
        
        if not tasks:
            return ""
        
        mermaid_content = "flowchart TD\n"
        
        # Add task nodes
        for task in tasks:
            node_id = task['id'].replace('-', '_')
            status_color = {
                'Not Started': 'fill:#ff9999',
                'In Progress': 'fill:#ffcc99',
                'Blocked': 'fill:#ff6666',
                'Complete': 'fill:#99ff99',
                'Abandoned': 'fill:#cccccc'
            }.get(task['status'], 'fill:#ffffff')
            
            title_short = task['title'][:30] + "..." if len(task['title']) > 30 else task['title']
            mermaid_content += f"    {node_id}[\"{task['id']}<br/>{title_short}\"]\n"
            mermaid_content += f"    style {node_id} {status_color}\n"
            
            # Add parent-child relationships
            if task['parent_task_id']:
                parent_id = task['parent_task_id'].replace('-', '_')
                mermaid_content += f"    {parent_id} --> {node_id}\n"
        
        return mermaid_content
    
    def _generate_architecture_diagram(self, requirement_ids: List[str] = None) -> str:
        """Generate architecture decisions diagram"""
        if requirement_ids:
            # Get architecture decisions for specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            architecture = self.db.execute_query(f"""
                SELECT DISTINCT a.* FROM architecture a
                JOIN requirement_architecture ra ON a.id = ra.architecture_id
                WHERE ra.requirement_id IN ({placeholders})
                ORDER BY a.created_at DESC
            """, requirement_ids, fetch_all=True, row_factory=True)
        else:
            architecture = self.db.get_records(
                "architecture",
                "*",
                order_by="created_at DESC"
            )
        
        if not architecture:
            return ""
        
        mermaid_content = "flowchart TD\n"
        
        for arch in architecture:
            node_id = arch['id'].replace('-', '_')
            status_color = {
                'Proposed': 'fill:#ffcc99',
                'Accepted': 'fill:#99ff99',
                'Rejected': 'fill:#ff9999',
                'Deprecated': 'fill:#cccccc',
                'Superseded': 'fill:#cccccc'
            }.get(arch['status'], 'fill:#ffffff')
            
            title_short = arch['title'][:30] + "..." if len(arch['title']) > 30 else arch['title']
            mermaid_content += f"    {node_id}[\"{arch['id']}<br/>{title_short}\"]\n"
            mermaid_content += f"    style {node_id} {status_color}\n"
        
        return mermaid_content
    
    def _generate_full_project_diagram(self, include_relationships: bool, requirement_ids: List[str] = None) -> str:
        """Generate full project overview diagram"""
        if requirement_ids:
            # Filter to specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            requirements = self.db.execute_query(
                f"SELECT * FROM requirements WHERE id IN ({placeholders}) ORDER BY type, requirement_number",
                requirement_ids,
                fetch_all=True,
                row_factory=True
            )
            tasks = self.db.execute_query(f"""
                SELECT DISTINCT t.* FROM tasks t
                JOIN requirement_tasks rt ON t.id = rt.task_id
                WHERE rt.requirement_id IN ({placeholders})
                ORDER BY t.task_number, t.subtask_number
            """, requirement_ids, fetch_all=True, row_factory=True)
            architecture = self.db.execute_query(f"""
                SELECT DISTINCT a.* FROM architecture a
                JOIN requirement_architecture ra ON a.id = ra.architecture_id
                WHERE ra.requirement_id IN ({placeholders})
                ORDER BY a.created_at DESC
            """, requirement_ids, fetch_all=True, row_factory=True)
        else:
            requirements = self.db.get_records("requirements", "*", order_by="type, requirement_number")
            tasks = self.db.get_records("tasks", "*", order_by="task_number, subtask_number")
            architecture = self.db.get_records("architecture", "*", order_by="created_at DESC")
        
        mermaid_content = "flowchart TD\n"
        mermaid_content += "    Requirements[Requirements]\n"
        mermaid_content += "    Tasks[Tasks]\n"
        mermaid_content += "    Architecture[Architecture]\n"
        
        # Add requirements (limit to first 10)
        for req in requirements[:10]:
            node_id = req['id'].replace('-', '_')
            title_short = req['title'][:20] + "..." if len(req['title']) > 20 else req['title']
            mermaid_content += f"    {node_id}[\"{req['id']}<br/>{title_short}\"]\n"
            mermaid_content += f"    Requirements --> {node_id}\n"
        
        # Add tasks (limit to first 10)
        for task in tasks[:10]:
            node_id = task['id'].replace('-', '_')
            title_short = task['title'][:20] + "..." if len(task['title']) > 20 else task['title']
            mermaid_content += f"    {node_id}[\"{task['id']}<br/>{title_short}\"]\n"
            mermaid_content += f"    Tasks --> {node_id}\n"
        
        # Add architecture (limit to first 5)
        for arch in architecture[:5]:
            node_id = arch['id'].replace('-', '_')
            title_short = arch['title'][:20] + "..." if len(arch['title']) > 20 else arch['title']
            mermaid_content += f"    {node_id}[\"{arch['id']}<br/>{title_short}\"]\n"
            mermaid_content += f"    Architecture --> {node_id}\n"
        
        # Add relationships if requested
        if include_relationships:
            req_tasks = self.db.execute_query("""
                SELECT rt.requirement_id, rt.task_id 
                FROM requirement_tasks rt
                LIMIT 20
            """, fetch_all=True, row_factory=True)
            
            for rt in req_tasks:
                req_id = rt['requirement_id'].replace('-', '_')
                task_id = rt['task_id'].replace('-', '_')
                mermaid_content += f"    {req_id} -.-> {task_id}\n"
        
        return mermaid_content
    
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
    
    def _generate_dependencies_diagram(self, requirement_ids: List[str] = None) -> str:
        """Generate dependencies diagram"""
        if requirement_ids:
            # Get task dependencies for specific requirements
            placeholders = ",".join(["?"] * len(requirement_ids))
            task_ids_query = self.db.execute_query(f"""
                SELECT DISTINCT task_id FROM requirement_tasks
                WHERE requirement_id IN ({placeholders})
            """, requirement_ids, fetch_all=True, row_factory=True)
            
            task_ids = [row['task_id'] for row in task_ids_query]
            if task_ids:
                task_placeholders = ",".join(["?"] * len(task_ids))
                dependencies = self.db.execute_query(f"""
                    SELECT td.task_id, td.depends_on_task_id 
                    FROM task_dependencies td
                    JOIN tasks t1 ON td.task_id = t1.id
                    JOIN tasks t2 ON td.depends_on_task_id = t2.id
                    WHERE td.task_id IN ({task_placeholders}) 
                       OR td.depends_on_task_id IN ({task_placeholders})
                """, task_ids + task_ids, fetch_all=True, row_factory=True)
            else:
                dependencies = []
        else:
            dependencies = self.db.execute_query("""
                SELECT td.task_id, td.depends_on_task_id 
                FROM task_dependencies td
                JOIN tasks t1 ON td.task_id = t1.id
                JOIN tasks t2 ON td.depends_on_task_id = t2.id
            """, fetch_all=True, row_factory=True)
        
        if not dependencies:
            return "flowchart TD\n    NoDeps[No task dependencies found]\n"
        
        mermaid_content = "flowchart TD\n"
        
        for dep in dependencies:
            task_id = dep['task_id'].replace('-', '_')
            depends_on = dep['depends_on_task_id'].replace('-', '_')
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
        safe_diagram_type = diagram_type.replace('_', '-').lower()
        
        # Generate timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d-%H%M%S')
        
        # Get file extension
        extension = self._get_diagram_file_extension(output_format)
        
        return f"{safe_diagram_type}-diagram-{timestamp}{extension}"
    
    def _validate_output_path(self, output_path: str) -> bool:
        """Validate output path for security (prevent path traversal)"""
        if not output_path:
            return False
        
        # Check for path traversal attempts
        if '..' in output_path:
            return False
        
        # Additional safety checks could be added here
        return True
    
    def _ensure_output_directory(self, output_path: str) -> bool:
        """Create output directory if it doesn't exist"""
        try:
            os.makedirs(output_path, exist_ok=True)
            return True
        except (OSError, PermissionError) as e:
            return False