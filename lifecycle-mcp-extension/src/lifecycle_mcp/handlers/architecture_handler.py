#!/usr/bin/env python3
"""
Architecture Handler for MCP Lifecycle Management Server
Handles all architecture decision-related operations
"""

import json
from typing import List, Dict, Any, Optional
from mcp.types import TextContent

from .base_handler import BaseHandler


class ArchitectureHandler(BaseHandler):
    """Handler for architecture decision-related MCP tools"""
    
    def __init__(self, db_manager, mcp_client=None):
        """Initialize handler with database manager and optional MCP client"""
        super().__init__(db_manager)
        self.mcp_client = mcp_client
    
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
                return await self._create_architecture_decision(**arguments)
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
    
    async def _create_architecture_decision(self, **params) -> List[TextContent]:
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
            
            # Analyze ADR for diagram suggestions using LLM
            diagram_suggestions = await self._analyze_adr_for_diagrams(arch_data)
            
            if diagram_suggestions and diagram_suggestions.get("suggested_diagrams"):
                # Format diagram suggestions for user
                suggestions_text = self._format_diagram_suggestions(diagram_suggestions, adr_id)
                key_info = f"Architecture decision {adr_id} created with diagram suggestions"
                action_info = f"📐 {params['title']} | {len(diagram_suggestions['suggested_diagrams'])} diagram suggestions"
                return self._create_above_fold_response("SUCCESS", key_info, action_info, suggestions_text)
            else:
                # Standard response without suggestions
                key_info = f"Architecture decision {adr_id} created"
                action_info = f"📐 {params['title']} | {params.get('status', 'Proposed')} | ADR"
                return self._create_above_fold_response("SUCCESS", key_info, action_info)
            
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
            
            # Create above-the-fold response
            key_info = f"Architecture {params['architecture_id']} updated"
            action_info = f"📈 {current_status} → {new_status}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info)
            
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
                return self._create_above_fold_response("INFO", "No architecture decisions found", "Try adjusting search criteria")
            
            # Build filter description for above-the-fold
            filters = []
            if params.get("status"):
                filters.append(f"status: {params['status']}")
            if params.get("requirement_id"):
                filters.append(f"requirement: {params['requirement_id']}")
            if params.get("search_text"):
                filters.append(f"search: {params['search_text']}")
            filter_desc = " | ".join(filters) if filters else "all decisions"
            
            # Build detailed list
            decision_list = []
            for decision in decisions:
                decision_info = f"- {decision['id']}: {decision['title']} [{decision['status']}] ({decision['type']})"
                decision_list.append(decision_info)
            
            key_info = self._format_count_summary("architecture decision", len(decisions), filter_desc)
            details = "\n".join(decision_list)
            
            return self._create_above_fold_response("SUCCESS", key_info, "", details)
            
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
            
            # Create above-the-fold response for architecture details
            key_info = f"Architecture {arch['id']} details"
            action_info = f"📐 {arch['title']} | {arch['status']} | {arch.get('type', 'ADR')}"
            return self._create_above_fold_response("INFO", key_info, action_info, report)
            
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
            
            # Create above-the-fold response
            key_info = f"Review added to {params['architecture_id']}"
            action_info = f"📝 Review by {params.get('reviewer', 'MCP User')}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info)
            
        except Exception as e:
            return self._create_error_response("Failed to add review", e)
    
    async def _analyze_adr_for_diagrams(self, adr_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyze ADR context using LLM sampling to suggest relevant diagrams"""
        if not self.mcp_client:
            self.logger.info("No MCP client available for sampling - skipping diagram suggestions")
            return None
            
        try:
            # Build context for LLM analysis
            adr_context = self._build_adr_context(adr_data)
            
            # Prepare LLM sampling request
            sampling_request = {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": adr_context
                        }
                    }
                ],
                "modelPreferences": {
                    "intelligencePriority": 0.8,
                    "speedPriority": 0.2,
                    "costPriority": 0.1
                },
                "systemPrompt": self._get_diagram_analysis_system_prompt(),
                "includeContext": "thisServer",
                "temperature": 0.1,
                "maxTokens": 800,
                "stopSequences": ["```"]
            }
            
            # Check if the MCP client has sampling capability
            if hasattr(self.mcp_client, 'sample') and callable(getattr(self.mcp_client, 'sample')):
                try:
                    # Make the actual MCP sampling request
                    response = await self.mcp_client.sample(sampling_request)
                    if response and hasattr(response, 'content') and hasattr(response.content, 'text'):
                        return json.loads(response.content.text)
                    else:
                        self.logger.warning("MCP sampling returned invalid response format")
                        return None
                except Exception as sampling_error:
                    self.logger.warning(f"MCP sampling failed: {sampling_error}")
                    return None
            else:
                self.logger.info("MCP client does not support sampling - skipping diagram suggestions")
                return None
            
        except Exception as e:
            # Log error but don't fail ADR creation
            self.logger.warning(f"LLM diagram analysis failed: {e}")
            return None
    
    def _build_adr_context(self, adr_data: Dict[str, Any]) -> str:
        """Build context string for ADR diagram analysis"""
        decision_drivers = self._safe_json_loads(adr_data.get("decision_drivers", "[]"))
        considered_options = self._safe_json_loads(adr_data.get("considered_options", "[]"))
        consequences = self._safe_json_loads(adr_data.get("consequences", "{}"))
        
        context = f"""Analyze this Architecture Decision Record (ADR) to suggest helpful diagrams for implementation and understanding:

**ADR Title**: {adr_data['title']}

**Context**: {adr_data['context']}

**Decision**: {adr_data['decision_outcome']}

**Decision Drivers**:
{self._format_list_items(decision_drivers)}

**Considered Options**:
{self._format_list_items(considered_options)}

**Consequences**:
{self._format_consequences(consequences)}

Please analyze this ADR and suggest 2-4 diagrams that would:
1. Help developers implement this decision effectively
2. Enhance stakeholder understanding of the architecture
3. Document key relationships and dependencies
4. Support future maintenance and evolution

Focus on practical diagrams that provide real implementation value.

Respond with valid JSON in this format:
{{
  "analysis": {{
    "architectural_scope": "component|system|integration|deployment",
    "complexity_level": 1-5,
    "implementation_focus": "string describing main implementation challenges"
  }},
  "suggested_diagrams": [
    {{
      "type": "requirements|tasks|architecture|full_project|dependencies",
      "title": "Descriptive diagram title",
      "purpose": "implementation|understanding|documentation|maintenance",
      "rationale": "Why this diagram helps with the ADR implementation",
      "priority": "high|medium|low"
    }}
  ],
  "implementation_notes": "Additional context for using these diagrams during implementation"
}}"""
        return context
    
    def _format_list_items(self, items: List[str]) -> str:
        """Format list items for context"""
        if not items:
            return "- None specified"
        return "\n".join(f"- {item}" for item in items)
    
    def _format_consequences(self, consequences: Dict[str, Any]) -> str:
        """Format consequences object for context"""
        if not consequences:
            return "- None specified"
        
        formatted = []
        if isinstance(consequences, dict):
            for key, value in consequences.items():
                if isinstance(value, list):
                    formatted.append(f"**{key.title()}**:")
                    formatted.extend(f"  - {item}" for item in value)
                else:
                    formatted.append(f"**{key.title()}**: {value}")
        else:
            formatted.append(str(consequences))
        
        return "\n".join(formatted) if formatted else "- None specified"
    
    def _get_diagram_analysis_system_prompt(self) -> str:
        """Get system prompt for ADR diagram analysis"""
        return """You are an expert software architect analyzing Architecture Decision Records (ADRs) to suggest helpful diagrams.

Your goal is to recommend diagrams that provide practical value for:
- Implementation teams who need to understand how to build the solution
- Stakeholders who need to understand the architectural impact
- Future maintainers who need to understand the system structure

Guidelines:
- Prioritize diagrams that directly support implementation activities
- Consider both technical and communication needs
- Focus on diagrams that show relationships, dependencies, and data flows
- Avoid suggesting diagrams that would be too simple or too complex for the context
- Always provide clear rationale for each suggestion
- Limit suggestions to 2-4 most valuable diagrams
- Always respond with valid JSON matching the specified format"""
    
    def _format_diagram_suggestions(self, suggestions: Dict[str, Any], adr_id: str) -> str:
        """Format diagram suggestions for user response"""
        suggested_diagrams = suggestions.get("suggested_diagrams", [])
        implementation_notes = suggestions.get("implementation_notes", "")
        
        response = f"""# Diagram Suggestions for {adr_id}

Based on your ADR content, I recommend the following diagrams to support implementation and understanding:

"""
        
        for i, diagram in enumerate(suggested_diagrams, 1):
            priority_emoji = {"high": "🔥", "medium": "⭐", "low": "💡"}.get(diagram.get("priority", "medium"), "⭐")
            purpose_emoji = {
                "implementation": "🔧", 
                "understanding": "📖", 
                "documentation": "📋", 
                "maintenance": "🔍"
            }.get(diagram.get("purpose", "implementation"), "🔧")
            
            response += f"""{i}. {priority_emoji} **{diagram['title']}** {purpose_emoji}
   - **Type**: {diagram['type']}
   - **Purpose**: {diagram['purpose'].title()}
   - **Rationale**: {diagram['rationale']}

"""
        
        if implementation_notes:
            response += f"""## Implementation Notes
{implementation_notes}

"""
        
        response += f"""## Next Steps
To generate these diagrams, use the `create_architectural_diagrams` tool:
- For individual diagrams: specify the `diagram_type` (e.g., "requirements", "architecture")
- For custom diagrams: use the interactive mode with `"interactive": true`

Example: `create_architectural_diagrams(diagram_type="architecture", output_format="markdown_with_mermaid")`
"""
        
        return response