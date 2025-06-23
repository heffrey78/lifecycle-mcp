#!/usr/bin/env python3
"""
Architecture Handler for MCP Lifecycle Management Server
Handles all architecture decision-related operations
"""

import json
from typing import List, Dict, Any
from mcp.types import TextContent

from .base_handler import BaseHandler


class ArchitectureHandler(BaseHandler):
    """Handler for architecture decision-related MCP tools"""
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return architecture tool definitions"""
        return [
            {
                "name": "create_architecture_decision",
                "description": "Record architecture decision (ADR)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_ids": {"type": "array", "items": {"type": "string"}},
                        "title": {"type": "string"},
                        "context": {"type": "string"},
                        "decision": {"type": "string"},
                        "consequences": {"type": "object"},
                        "decision_drivers": {"type": "array", "items": {"type": "string"}},
                        "considered_options": {"type": "array", "items": {"type": "string"}},
                        "authors": {"type": "array", "items": {"type": "string"}}
                    },
                    "required": ["requirement_ids", "title", "context", "decision"]
                }
            },
            {
                "name": "update_architecture_status",
                "description": "Update architecture decision status",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "architecture_id": {"type": "string"},
                        "new_status": {"type": "string", "enum": [
                            "Proposed", "Accepted", "Rejected", "Deprecated", "Superseded",
                            "Draft", "Under Review", "Approved", "Implemented"
                        ]},
                        "comment": {"type": "string"}
                    },
                    "required": ["architecture_id", "new_status"]
                }
            },
            {
                "name": "query_architecture_decisions",
                "description": "Search and filter architecture decisions",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "type": {"type": "string"},
                        "requirement_id": {"type": "string"},
                        "search_text": {"type": "string"}
                    }
                }
            },
            {
                "name": "get_architecture_details",
                "description": "Get full architecture decision details",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "architecture_id": {"type": "string"}
                    },
                    "required": ["architecture_id"]
                }
            },
            {
                "name": "add_architecture_review",
                "description": "Add review comment to architecture decision",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "architecture_id": {"type": "string"},
                        "comment": {"type": "string"},
                        "reviewer": {"type": "string"}
                    },
                    "required": ["architecture_id", "comment"]
                }
            }
        ]
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_architecture_decision":
                return self._create_architecture_decision(**arguments)
            elif tool_name == "update_architecture_status":
                return self._update_architecture_status(**arguments)
            elif tool_name == "query_architecture_decisions":
                return self._query_architecture_decisions(**arguments)
            elif tool_name == "get_architecture_details":
                return self._get_architecture_details(**arguments)
            elif tool_name == "add_architecture_review":
                return self._add_architecture_review(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)
    
    def _create_architecture_decision(self, **params) -> List[TextContent]:
        """Create ADR"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_ids", "title", "context", "decision"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get next ADR number
            adr_number = self.db.execute_query("""
                SELECT COALESCE(MAX(CAST(SUBSTR(id, 5, 4) AS INTEGER)), 0) + 1 
                FROM architecture 
                WHERE type = 'ADR'
            """, fetch_one=True)[0]
            
            adr_id = f"ADR-{adr_number:04d}"
            
            # Prepare architecture data
            arch_data = {
                "id": adr_id,
                "type": "ADR",
                "title": params["title"],
                "status": "Proposed",
                "context": params["context"],
                "decision_outcome": params["decision"],
                "decision_drivers": self._safe_json_dumps(params.get("decision_drivers", [])),
                "considered_options": self._safe_json_dumps(params.get("considered_options", [])),
                "consequences": self._safe_json_dumps(params.get("consequences", {})),
                "authors": self._safe_json_dumps(params.get("authors", ["MCP User"]))
            }
            
            # Insert ADR
            self.db.insert_record("architecture", arch_data)
            
            # Link to requirements
            for req_id in params["requirement_ids"]:
                self.db.insert_record("requirement_architecture", {
                    "requirement_id": req_id,
                    "architecture_id": adr_id,
                    "relationship_type": "addresses"
                })
            
            return self._create_response(f"Created architecture decision {adr_id}: {params['title']}")
            
        except Exception as e:
            return self._create_error_response("Failed to create architecture decision", e)
    
    def _update_architecture_status(self, **params) -> List[TextContent]:
        """Update architecture decision status"""
        # Validate required parameters
        error = self._validate_required_params(params, ["architecture_id", "new_status"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get current status
            current_arch = self.db.get_records(
                "architecture",
                "status",
                "id = ?",
                [params["architecture_id"]]
            )
            
            if not current_arch:
                return self._create_error_response("Architecture decision not found")
            
            current_status = current_arch[0]["status"]
            new_status = params["new_status"]
            
            # Update status
            self.db.update_record(
                "architecture",
                {"status": new_status, "updated_at": "CURRENT_TIMESTAMP"},
                "id = ?",
                [params["architecture_id"]]
            )
            
            # Add review comment if provided
            if params.get("comment"):
                self._add_review_comment("architecture", params["architecture_id"], params["comment"])
            
            return self._create_response(
                f"Updated {params['architecture_id']} from {current_status} to {new_status}"
            )
            
        except Exception as e:
            return self._create_error_response("Failed to update architecture status", e)
    
    def _query_architecture_decisions(self, **params) -> List[TextContent]:
        """Query architecture decisions with filters"""
        try:
            where_clauses = []
            where_params = []
            base_query = "SELECT * FROM architecture"
            
            # Handle requirement_id filter specially (requires join)
            if params.get("requirement_id"):
                base_query = """
                    SELECT a.* FROM architecture a
                    JOIN requirement_architecture ra ON a.id = ra.architecture_id
                    WHERE ra.requirement_id = ?
                """
                where_params.append(params["requirement_id"])
                
                # Add additional filters for the joined query
                if params.get("search_text"):
                    where_clauses.append("(a.title LIKE ? OR a.context LIKE ?)")
                    search = f"%{params['search_text']}%"
                    where_params.extend([search, search])
            else:
                # Build standard filters
                if params.get("status"):
                    where_clauses.append("status = ?")
                    where_params.append(params["status"])
                
                if params.get("type"):
                    where_clauses.append("type = ?")
                    where_params.append(params["type"])
                
                if params.get("search_text"):
                    where_clauses.append("(title LIKE ? OR context LIKE ?)")
                    search = f"%{params['search_text']}%"
                    where_params.extend([search, search])
            
            # Construct final query
            if where_clauses:
                if "WHERE" in base_query:
                    base_query += " AND " + " AND ".join(where_clauses)
                else:
                    base_query += " WHERE " + " AND ".join(where_clauses)
            
            base_query += " ORDER BY created_at DESC"
            
            decisions = self.db.execute_query(base_query, where_params, fetch_all=True, row_factory=True)
            
            if not decisions:
                return self._create_response("No architecture decisions found matching criteria")
            
            result = f"Found {len(decisions)} architecture decisions:\n\n"
            for decision in decisions:
                result += f"- {decision['id']}: {decision['title']} [{decision['status']}] ({decision['type']})\n"
            
            return self._create_response(result)
            
        except Exception as e:
            return self._create_error_response("Failed to query architecture decisions", e)
    
    def _get_architecture_details(self, **params) -> List[TextContent]:
        """Get full architecture decision details"""
        # Validate required parameters
        error = self._validate_required_params(params, ["architecture_id"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Get architecture decision
            arch_decisions = self.db.get_records(
                "architecture",
                "*",
                "id = ?",
                [params["architecture_id"]]
            )
            
            if not arch_decisions:
                return self._create_error_response("Architecture decision not found")
            
            arch = arch_decisions[0]
            
            # Build detailed report
            report = f"""# Architecture Decision: {arch['id']}

## Basic Information
- **Title**: {arch['title']}
- **Type**: {arch['type']}
- **Status**: {arch['status']}
- **Created**: {arch['created_at']}
- **Updated**: {arch['updated_at']}
- **Authors**: {arch['authors'] or 'Not specified'}

## Context
{arch['context']}

## Decision
{arch['decision_outcome']}
"""
            
            if arch['decision_drivers']:
                drivers = self._safe_json_loads(arch['decision_drivers'])
                if drivers:
                    report += "\n## Decision Drivers\n"
                    for driver in drivers:
                        report += f"- {driver}\n"
            
            if arch['considered_options']:
                options = self._safe_json_loads(arch['considered_options'])
                if options:
                    report += "\n## Considered Options\n"
                    for option in options:
                        report += f"- {option}\n"
            
            if arch['consequences']:
                consequences = self._safe_json_loads(arch['consequences'])
                if consequences:
                    report += "\n## Consequences\n"
                    if isinstance(consequences, dict):
                        for key, value in consequences.items():
                            report += f"**{key.title()}**: {value}\n"
                    else:
                        report += f"{consequences}\n"
            
            # Get linked requirements
            requirements = self.db.execute_query("""
                SELECT r.id, r.title FROM requirements r
                JOIN requirement_architecture ra ON r.id = ra.requirement_id
                WHERE ra.architecture_id = ?
            """, [params["architecture_id"]], fetch_all=True, row_factory=True)
            
            if requirements:
                report += f"\n## Linked Requirements ({len(requirements)})\n"
                for req in requirements:
                    report += f"- {req['id']}: {req['title']}\n"
            
            # Get reviews
            reviews = self.db.execute_query("""
                SELECT reviewer, comment, created_at FROM reviews
                WHERE entity_type = 'architecture' AND entity_id = ?
                ORDER BY created_at DESC
            """, [params["architecture_id"]], fetch_all=True, row_factory=True)
            
            if reviews:
                report += f"\n## Reviews ({len(reviews)})\n"
                for review in reviews:
                    report += f"- **{review['reviewer']}** ({review['created_at']}): {review['comment']}\n"
            
            return self._create_response(report)
            
        except Exception as e:
            return self._create_error_response("Failed to get architecture details", e)
    
    def _add_architecture_review(self, **params) -> List[TextContent]:
        """Add review comment to architecture decision"""
        # Validate required parameters
        error = self._validate_required_params(params, ["architecture_id", "comment"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Verify architecture exists
            if not self.db.check_exists("architecture", "id = ?", [params["architecture_id"]]):
                return self._create_error_response("Architecture decision not found")
            
            # Add review
            self._add_review_comment(
                "architecture", 
                params["architecture_id"], 
                params["comment"],
                params.get("reviewer", "MCP User")
            )
            
            return self._create_response(f"Added review to {params['architecture_id']}")
            
        except Exception as e:
            return self._create_error_response("Failed to add review", e)