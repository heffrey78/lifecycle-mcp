#!/usr/bin/env python3
"""
Requirement Handler for MCP Lifecycle Management Server
Handles all requirement-related operations
"""

import json
from typing import List, Dict, Any
from mcp.types import TextContent

from .base_handler import BaseHandler


class RequirementHandler(BaseHandler):
    """Handler for requirement-related MCP tools"""
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return requirement tool definitions"""
        return [
            {
                "name": "create_requirement",
                "description": "Create a new requirement from interview data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["FUNC", "NFUNC", "TECH", "BUS", "INTF"]},
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                        "current_state": {"type": "string"},
                        "desired_state": {"type": "string"},
                        "functional_requirements": {"type": "array", "items": {"type": "string"}},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "business_value": {"type": "string"},
                        "risk_level": {"type": "string", "enum": ["High", "Medium", "Low"]},
                        "author": {"type": "string"}
                    },
                    "required": ["type", "title", "priority", "current_state", "desired_state"]
                }
            },
            {
                "name": "update_requirement_status",
                "description": "Move requirement through lifecycle states",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"},
                        "new_status": {"type": "string", "enum": [
                            "Draft", "Under Review", "Approved", "Architecture", 
                            "Ready", "Implemented", "Validated", "Deprecated"
                        ]},
                        "comment": {"type": "string"}
                    },
                    "required": ["requirement_id", "new_status"]
                }
            },
            {
                "name": "query_requirements",
                "description": "Search and filter requirements",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "priority": {"type": "string"},
                        "type": {"type": "string"},
                        "search_text": {"type": "string"}
                    }
                }
            },
            {
                "name": "get_requirement_details",
                "description": "Get full requirement with all relationships",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"}
                    },
                    "required": ["requirement_id"]
                }
            },
            {
                "name": "trace_requirement",
                "description": "Trace requirement through implementation",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"}
                    },
                    "required": ["requirement_id"]
                }
            }
        ]
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_requirement":
                return self._create_requirement(**arguments)
            elif tool_name == "update_requirement_status":
                return self._update_requirement_status(**arguments)
            elif tool_name == "query_requirements":
                return self._query_requirements(**arguments)
            elif tool_name == "get_requirement_details":
                return self._get_requirement_details(**arguments)
            elif tool_name == "trace_requirement":
                return self._trace_requirement(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)
    
    def _create_requirement(self, **params) -> List[TextContent]:
        """Create a new requirement"""
        # Validate required parameters
        error = self._validate_required_params(params, ["type", "title", "priority", "current_state", "desired_state"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get next requirement number
            req_number = self.db.get_next_id("requirements", "requirement_number", "type = ?", [params["type"]])
            req_id = f"REQ-{req_number:04d}-{params['type']}-00"
            
            # Prepare requirement data
            req_data = {
                "id": req_id,
                "requirement_number": req_number,
                "type": params["type"],
                "version": 0,
                "title": params["title"],
                "priority": params["priority"],
                "current_state": params["current_state"],
                "desired_state": params["desired_state"],
                "functional_requirements": self._safe_json_dumps(params.get("functional_requirements", [])),
                "acceptance_criteria": self._safe_json_dumps(params.get("acceptance_criteria", [])),
                "author": params.get("author", "MCP User"),
                "business_value": params.get("business_value", ""),
                "risk_level": params.get("risk_level", "Medium")
            }
            
            # Insert requirement
            self.db.insert_record("requirements", req_data)
            
            # Log event
            self._log_operation("requirement", req_id, "created", params.get("author", "MCP User"))
            
            return self._create_response(f"Created requirement {req_id}: {params['title']}")
            
        except Exception as e:
            return self._create_error_response("Failed to create requirement", e)
    
    def _update_requirement_status(self, **params) -> List[TextContent]:
        """Update requirement status with validation"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_id", "new_status"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get current status
            current_req = self.db.get_records(
                "requirements", 
                "status", 
                "id = ?", 
                [params["requirement_id"]]
            )
            
            if not current_req:
                return self._create_error_response("Requirement not found")
            
            current_status = current_req[0]["status"]
            new_status = params["new_status"]
            
            # Validate state transition
            valid_transitions = {
                "Draft": ["Under Review", "Deprecated"],
                "Under Review": ["Draft", "Approved", "Deprecated"],
                "Approved": ["Architecture", "Ready", "Deprecated"],
                "Architecture": ["Ready", "Approved"],
                "Ready": ["Implemented", "Deprecated"],
                "Implemented": ["Validated", "Ready"],
                "Validated": ["Deprecated"],
                "Deprecated": []
            }
            
            if new_status not in valid_transitions.get(current_status, []):
                return self._create_error_response(
                    f"Invalid transition from {current_status} to {new_status}"
                )
            
            # Update status
            self.db.update_record(
                "requirements",
                {"status": new_status, "updated_at": "CURRENT_TIMESTAMP"},
                "id = ?",
                [params["requirement_id"]]
            )
            
            # Add review comment if provided
            if params.get("comment"):
                self._add_review_comment("requirement", params["requirement_id"], params["comment"])
            
            return self._create_response(
                f"Updated {params['requirement_id']} from {current_status} to {new_status}"
            )
            
        except Exception as e:
            return self._create_error_response("Failed to update requirement status", e)
    
    def _query_requirements(self, **params) -> List[TextContent]:
        """Query requirements with filters"""
        try:
            where_clauses = []
            where_params = []
            
            if params.get("status"):
                where_clauses.append("status = ?")
                where_params.append(params["status"])
            
            if params.get("priority"):
                where_clauses.append("priority = ?")
                where_params.append(params["priority"])
            
            if params.get("type"):
                where_clauses.append("type = ?")
                where_params.append(params["type"])
            
            if params.get("search_text"):
                where_clauses.append("(title LIKE ? OR desired_state LIKE ?)")
                search = f"%{params['search_text']}%"
                where_params.extend([search, search])
            
            where_clause = " AND ".join(where_clauses) if where_clauses else ""
            
            requirements = self.db.get_records(
                "requirements",
                "*",
                where_clause,
                where_params,
                "priority, created_at DESC"
            )
            
            if not requirements:
                return self._create_response("No requirements found matching criteria")
            
            result = f"Found {len(requirements)} requirements:\n\n"
            for req in requirements:
                result += f"- {req['id']}: {req['title']} [{req['status']}] {req['priority']}\n"
            
            return self._create_response(result)
            
        except Exception as e:
            return self._create_error_response("Failed to query requirements", e)
    
    def _get_requirement_details(self, **params) -> List[TextContent]:
        """Get full requirement details"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_id"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get requirement
            requirements = self.db.get_records(
                "requirements",
                "*",
                "id = ?",
                [params["requirement_id"]]
            )
            
            if not requirements:
                return self._create_error_response("Requirement not found")
            
            req = requirements[0]
            
            # Build detailed report
            report = f"""# Requirement Details: {req['id']}

## Basic Information
- **Title**: {req['title']}
- **Type**: {req['type']}
- **Status**: {req['status']}
- **Priority**: {req['priority']}
- **Risk Level**: {req['risk_level']}
- **Author**: {req['author']}
- **Created**: {req['created_at']}
- **Updated**: {req['updated_at']}

## Problem Definition
**Current State**: {req['current_state']}

**Desired State**: {req['desired_state']}

**Business Value**: {req['business_value'] or 'Not specified'}

## Requirements Details
"""
            
            if req['functional_requirements']:
                func_reqs = self._safe_json_loads(req['functional_requirements'])
                if func_reqs:
                    report += "### Functional Requirements\n"
                    for fr in func_reqs:
                        report += f"- {fr}\n"
            
            if req['acceptance_criteria']:
                acc_criteria = self._safe_json_loads(req['acceptance_criteria'])
                if acc_criteria:
                    report += "\n### Acceptance Criteria\n"
                    for ac in acc_criteria:
                        report += f"- {ac}\n"
            
            # Get linked tasks
            tasks = self.db.execute_query("""
                SELECT t.* FROM tasks t
                JOIN requirement_tasks rt ON t.id = rt.task_id
                WHERE rt.requirement_id = ?
            """, [params["requirement_id"]], fetch_all=True, row_factory=True)
            
            if tasks:
                report += f"\n## Linked Tasks ({len(tasks)})\n"
                for task in tasks:
                    report += f"- {task['id']}: {task['title']} [{task['status']}]\n"
            
            return self._create_response(report)
            
        except Exception as e:
            return self._create_error_response("Failed to get requirement details", e)
    
    def _trace_requirement(self, **params) -> List[TextContent]:
        """Trace requirement through full lifecycle"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_id"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get requirement
            requirements = self.db.get_records(
                "requirements",
                "*",
                "id = ?",
                [params["requirement_id"]]
            )
            
            if not requirements:
                return self._create_error_response("Requirement not found")
            
            req = requirements[0]
            
            # Get tasks
            tasks = self.db.execute_query("""
                SELECT t.* FROM tasks t
                JOIN requirement_tasks rt ON t.id = rt.task_id
                WHERE rt.requirement_id = ?
                ORDER BY t.task_number, t.subtask_number
            """, [params["requirement_id"]], fetch_all=True, row_factory=True)
            
            # Get architecture
            architecture = self.db.execute_query("""
                SELECT a.* FROM architecture a
                JOIN requirement_architecture ra ON a.id = ra.architecture_id
                WHERE ra.requirement_id = ?
            """, [params["requirement_id"]], fetch_all=True, row_factory=True)
            
            # Build trace report
            report = f"""# Requirement Trace: {req['id']}

## Requirement Details
- **Title**: {req['title']}
- **Status**: {req['status']}
- **Priority**: {req['priority']}
- **Created**: {req['created_at']}
- **Progress**: {req['tasks_completed']}/{req['task_count']} tasks complete

## Current State
{req['current_state']}

## Desired State
{req['desired_state']}

## Implementation Tasks ({len(tasks)})
"""
            for task in tasks:
                report += f"- {task['id']}: {task['title']} [{task['status']}]"
                if task['assignee']:
                    report += f" (Assigned: {task['assignee']})"
                report += "\n"
            
            if architecture:
                report += f"\n## Architecture Decisions ({len(architecture)})\n"
                for arch in architecture:
                    report += f"- {arch['id']}: {arch['title']} [{arch['status']}]\n"
            
            return self._create_response(report)
            
        except Exception as e:
            return self._create_error_response("Failed to trace requirement", e)