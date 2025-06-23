#!/usr/bin/env python3
"""
Task Handler for MCP Lifecycle Management Server
Handles all task-related operations
"""

import json
from typing import List, Dict, Any
from mcp.types import TextContent

from .base_handler import BaseHandler


class TaskHandler(BaseHandler):
    """Handler for task-related MCP tools"""
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return task tool definitions"""
        return [
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
                        "assignee": {"type": "string"}
                    },
                    "required": ["requirement_ids", "title", "priority"]
                }
            },
            {
                "name": "update_task_status",
                "description": "Update task progress",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "new_status": {"type": "string", "enum": [
                            "Not Started", "In Progress", "Blocked", "Complete", "Abandoned"
                        ]},
                        "comment": {"type": "string"},
                        "assignee": {"type": "string"}
                    },
                    "required": ["task_id", "new_status"]
                }
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
                        "requirement_id": {"type": "string"}
                    }
                }
            },
            {
                "name": "get_task_details",
                "description": "Get full task details with dependencies",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"}
                    },
                    "required": ["task_id"]
                }
            }
        ]
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_task":
                return self._create_task(**arguments)
            elif tool_name == "update_task_status":
                return self._update_task_status(**arguments)
            elif tool_name == "query_tasks":
                return self._query_tasks(**arguments)
            elif tool_name == "get_task_details":
                return self._get_task_details(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)
    
    def _create_task(self, **params) -> List[TextContent]:
        """Create task linked to requirements"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_ids", "title", "priority"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get next task number
            task_number = self.db.get_next_id("tasks", "task_number")
            
            # Determine subtask number
            subtask_number = 0
            if params.get("parent_task_id"):
                # For subtasks, find the parent's task number and get next subtask number
                parent_info = self.db.get_records(
                    "tasks",
                    "task_number",
                    "id = ?",
                    [params["parent_task_id"]]
                )
                
                if parent_info:
                    parent_task_number = parent_info[0]["task_number"]
                    subtask_number = self.db.get_next_id(
                        "tasks", 
                        "subtask_number", 
                        "parent_task_id = ?", 
                        [params["parent_task_id"]]
                    )
                    task_number = parent_task_number
            
            task_id = f"TASK-{task_number:04d}-{subtask_number:02d}-00"
            
            # Prepare task data
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
                "parent_task_id": params.get("parent_task_id"),
                "assignee": params.get("assignee")
            }
            
            # Insert task
            self.db.insert_record("tasks", task_data)
            
            # Link to requirements
            for req_id in params["requirement_ids"]:
                self.db.insert_record("requirement_tasks", {
                    "requirement_id": req_id,
                    "task_id": task_id
                })
            
            return self._create_response(f"Created task {task_id}: {params['title']}")
            
        except Exception as e:
            return self._create_error_response("Failed to create task", e)
    
    def _update_task_status(self, **params) -> List[TextContent]:
        """Update task status"""
        # Validate required parameters
        error = self._validate_required_params(params, ["task_id", "new_status"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get current task
            current_tasks = self.db.get_records(
                "tasks",
                "status, assignee",
                "id = ?",
                [params["task_id"]]
            )
            
            if not current_tasks:
                return self._create_error_response("Task not found")
            
            current_task = current_tasks[0]
            current_status = current_task["status"]
            new_status = params["new_status"]
            
            # Prepare update data
            update_data = {
                "status": new_status,
                "updated_at": "CURRENT_TIMESTAMP"
            }
            
            if params.get("assignee"):
                update_data["assignee"] = params["assignee"]
            
            # Update task
            self.db.update_record(
                "tasks",
                update_data,
                "id = ?",
                [params["task_id"]]
            )
            
            # Add comment if provided
            if params.get("comment"):
                self._add_review_comment("task", params["task_id"], params["comment"])
            
            return self._create_response(
                f"Updated task {params['task_id']} from {current_status} to {new_status}"
            )
            
        except Exception as e:
            return self._create_error_response("Failed to update task", e)
    
    def _query_tasks(self, **params) -> List[TextContent]:
        """Query tasks with filters"""
        try:
            where_clauses = []
            where_params = []
            
            # Handle requirement_id filter specially (requires join)
            if params.get("requirement_id"):
                tasks = self.db.execute_query("""
                    SELECT t.* FROM tasks t
                    JOIN requirement_tasks rt ON t.id = rt.task_id
                    WHERE rt.requirement_id = ?
                    ORDER BY t.priority, t.created_at DESC
                """, [params["requirement_id"]], fetch_all=True, row_factory=True)
            else:
                # Build standard filters
                if params.get("status"):
                    where_clauses.append("status = ?")
                    where_params.append(params["status"])
                
                if params.get("priority"):
                    where_clauses.append("priority = ?")
                    where_params.append(params["priority"])
                
                if params.get("assignee"):
                    where_clauses.append("assignee = ?")
                    where_params.append(params["assignee"])
                
                where_clause = " AND ".join(where_clauses) if where_clauses else ""
                
                tasks = self.db.get_records(
                    "tasks",
                    "*",
                    where_clause,
                    where_params,
                    "priority, created_at DESC"
                )
            
            if not tasks:
                return self._create_response("No tasks found matching criteria")
            
            result = f"Found {len(tasks)} tasks:\n\n"
            for task in tasks:
                result += f"- {task['id']}: {task['title']} [{task['status']}] {task['priority']}"
                if task['assignee']:
                    result += f" (Assigned: {task['assignee']})"
                result += "\n"
            
            return self._create_response(result)
            
        except Exception as e:
            return self._create_error_response("Failed to query tasks", e)
    
    def _get_task_details(self, **params) -> List[TextContent]:
        """Get full task details"""
        # Validate required parameters
        error = self._validate_required_params(params, ["task_id"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get task
            tasks = self.db.get_records(
                "tasks",
                "*",
                "id = ?",
                [params["task_id"]]
            )
            
            if not tasks:
                return self._create_error_response("Task not found")
            
            task = tasks[0]
            
            # Build report
            report = f"""# Task Details: {task['id']}

## Basic Information
- **Title**: {task['title']}
- **Status**: {task['status']}
- **Priority**: {task['priority']}
- **Effort**: {task['effort'] or 'Not specified'}
- **Assignee**: {task['assignee'] or 'Unassigned'}
- **Created**: {task['created_at']}
- **Updated**: {task['updated_at']}

## Description
{task['user_story'] or 'No user story provided'}

## Acceptance Criteria
"""
            
            if task['acceptance_criteria']:
                criteria = self._safe_json_loads(task['acceptance_criteria'])
                if criteria:
                    for criterion in criteria:
                        report += f"- {criterion}\n"
                else:
                    report += "No acceptance criteria defined\n"
            else:
                report += "No acceptance criteria defined\n"
            
            # Get linked requirements
            requirements = self.db.execute_query("""
                SELECT r.id, r.title FROM requirements r
                JOIN requirement_tasks rt ON r.id = rt.requirement_id
                WHERE rt.task_id = ?
            """, [params["task_id"]], fetch_all=True, row_factory=True)
            
            if requirements:
                report += f"\n## Linked Requirements ({len(requirements)})\n"
                for req in requirements:
                    report += f"- {req['id']}: {req['title']}\n"
            
            # Get subtasks if this is a parent task
            subtasks = self.db.get_records(
                "tasks",
                "id, title, status",
                "parent_task_id = ?",
                [params["task_id"]],
                "subtask_number"
            )
            
            if subtasks:
                report += f"\n## Subtasks ({len(subtasks)})\n"
                for subtask in subtasks:
                    report += f"- {subtask['id']}: {subtask['title']} [{subtask['status']}]\n"
            
            # Show parent task if this is a subtask
            if task['parent_task_id']:
                parent_tasks = self.db.get_records(
                    "tasks",
                    "id, title, status",
                    "id = ?",
                    [task['parent_task_id']]
                )
                
                if parent_tasks:
                    parent = parent_tasks[0]
                    report += f"\n## Parent Task\n"
                    report += f"- {parent['id']}: {parent['title']} [{parent['status']}]\n"
            
            return self._create_response(report)
            
        except Exception as e:
            return self._create_error_response("Failed to get task details", e)