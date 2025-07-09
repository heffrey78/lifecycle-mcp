#!/usr/bin/env python3
"""
Requirement Handler for MCP Lifecycle Management Server
Handles all requirement-related operations
"""

import json
from typing import Any, Dict, List, Optional

from mcp.types import TextContent

from .base_handler import BaseHandler


class RequirementHandler(BaseHandler):
    """Handler for requirement-related MCP tools"""
    
    def __init__(self, db_manager, mcp_client=None):
        """Initialize handler with database manager and optional MCP client"""
        super().__init__(db_manager)
        self.mcp_client = mcp_client
    
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
                return await self._create_requirement(**arguments)
            elif tool_name == "update_requirement_status":
                return await self._update_requirement_status(**arguments)
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
    
    async def _create_requirement(self, **params) -> List[TextContent]:
        """Create a new requirement with LLM-enhanced analysis"""
        # Validate required parameters
        error = self._validate_required_params(params, ["type", "title", "priority", "current_state", "desired_state"])
        if error:
            return self._create_error_response(error)
        
        try:
            # Perform LLM analysis for requirement decomposition
            llm_analysis = await self._analyze_requirement_with_llm(params)
            analysis_warning = ""
            
            # Handle LLM analysis results
            if llm_analysis:
                if llm_analysis.get("recommendation") == "needs_clarification":
                    # Return clarifying questions to user
                    return self._create_clarification_response(llm_analysis)
                elif llm_analysis.get("recommendation") == "decompose":
                    # Automatically create decomposed requirements
                    return await self._create_decomposed_requirements(llm_analysis, params)
            else:
                analysis_warning = "\n⚠️  LLM analysis not available - proceeding with standard creation"
            
            # Standard requirement creation (single requirement)
            req_id = self._create_single_requirement(params)
            
            # Create above-the-fold response
            key_info = f"Requirement {req_id} created"
            action_info = f"📄 {params['title']} | {params['type']} | {params['priority']}"
            warning_info = analysis_warning.strip() if analysis_warning else ""
            
            return self._create_above_fold_response("SUCCESS", key_info, action_info, warning_info)
            
        except Exception as e:
            return self._create_error_response("Failed to create requirement", e)
    
    async def _analyze_requirement_with_llm(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyze requirement using LLM sampling for decomposition"""
        if not self.mcp_client:
            self.logger.info("No MCP client available for sampling - using fallback requirement creation")
            return None
            
        try:
            # Build context for LLM analysis
            requirement_context = self._build_requirement_context(params)
            
            # Prepare LLM sampling request
            sampling_request = {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": requirement_context
                        }
                    }
                ],
                "modelPreferences": {
                    "intelligencePriority": 0.8,
                    "speedPriority": 0.2,
                    "costPriority": 0.1
                },
                "systemPrompt": self._get_analysis_system_prompt(),
                "includeContext": "thisServer",
                "temperature": 0.1,
                "maxTokens": 1000,
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
                self.logger.info("MCP client does not support sampling - using fallback requirement creation")
                return None
            
        except Exception as e:
            # Log error but don't fail requirement creation
            self.logger.warning(f"LLM analysis failed: {e}")
            return None
    
    def _build_requirement_context(self, params: Dict[str, Any]) -> str:
        """Build context string for LLM analysis"""
        context = f"""Analyze this requirement for decomposition and clarity:

Title: {params['title']}
Type: {params['type']}
Priority: {params['priority']}
Current State: {params['current_state']}
Desired State: {params['desired_state']}
Business Value: {params.get('business_value', 'Not specified')}

Functional Requirements:
{self._format_list(params.get('functional_requirements', []))}

Acceptance Criteria:
{self._format_list(params.get('acceptance_criteria', []))}

Please analyze if this requirement should be:
1. Created as a single requirement (good scope examples: "natural language search", 
   "unified navigation bar", "mobile friendly navigation")
2. Decomposed into sub-requirements (if it covers multiple features, pages, or complex workflows)
3. Needs clarification (missing critical details)

Respond with valid JSON in this format:
{{
  "analysis": {{
    "complexity_score": 1-10,
    "needs_decomposition": boolean,
    "scope_assessment": "single_feature|multiple_features|complex_workflow"
  }},
  "decomposition": {{
    "suggested_sub_requirements": [
      {{
        "title": "string",
        "type": "FUNC|NFUNC|TECH|BUS|INTF",
        "rationale": "string"
      }}
    ]
  }},
  "clarifying_questions": [
    {{
      "question": "string",
      "purpose": "scope|technical|business|acceptance"
    }}
  ],
  "recommendation": "create_single|decompose|needs_clarification"
}}"""
        return context
    
    def _get_analysis_system_prompt(self) -> str:
        """Get system prompt for LLM analysis"""
        return """You are an expert requirements analyst. Analyze requirements for proper scoping and decomposition.

Guidelines:
- Single requirements should be implementable as one cohesive feature
- Requirements covering multiple features, pages, or workflows need decomposition
- Ask 1-3 focused clarifying questions when requirements lack critical details
- Provide clear rationale for decomposition suggestions
- Always respond with valid JSON matching the specified format"""
    
    def _format_list(self, items: List[str]) -> str:
        """Format list items for context"""
        if not items:
            return "- None specified"
        return "\n".join(f"- {item}" for item in items)
    
    def _create_clarification_response(self, analysis: Dict[str, Any]) -> List[TextContent]:
        """Create response with clarifying questions"""
        questions = analysis.get("clarifying_questions", [])[:3]  # Limit to 3 questions
        
        response = "The requirement needs additional clarification. Please answer these questions:\n\n"
        for i, q in enumerate(questions, 1):
            response += f"{i}. {q['question']} (Purpose: {q['purpose']})\n"
        
        response += "\nOnce you provide answers, I can create a properly scoped requirement."
        
        # Create above-the-fold response for clarification
        key_info = "Requirement needs clarification"
        action_info = f"❓ {len(questions)} questions | Please provide details"
        return self._create_above_fold_response("INFO", key_info, action_info, response)
    
    def _create_decomposition_response(
        self, analysis: Dict[str, Any], original_params: Dict[str, Any]
    ) -> List[TextContent]:
        """Create response with decomposition suggestions"""
        suggestions = analysis.get("decomposition", {}).get("suggested_sub_requirements", [])
        
        response = f"The requirement '{original_params['title']}' should be decomposed into smaller requirements:\n\n"
        
        for i, suggestion in enumerate(suggestions, 1):
            response += f"{i}. **{suggestion['title']}** ({suggestion['type']})\n"
            response += f"   Rationale: {suggestion['rationale']}\n\n"
        
        response += "Would you like me to create these individual requirements instead?"
        
        # Create above-the-fold response for decomposition
        key_info = "Requirement should be decomposed"
        action_info = f"🔄 {len(suggestions)} sub-requirements suggested | Complex scope detected"
        return self._create_above_fold_response("INFO", key_info, action_info, response)
    
    def _create_single_requirement(self, params: Dict[str, Any]) -> str:
        """Create a single requirement (extracted from original logic)"""
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
        
        return req_id
    
    async def _create_decomposed_requirements(
        self, analysis: Dict[str, Any], original_params: Dict[str, Any]
    ) -> List[TextContent]:
        """Create decomposed sub-requirements automatically from LLM analysis"""
        try:
            suggestions = analysis.get("decomposition", {}).get("suggested_sub_requirements", [])
            
            if not suggestions:
                # Fallback to single requirement if no suggestions
                req_id = self._create_single_requirement(original_params)
                key_info = f"Requirement {req_id} created"
                req_type = original_params['type']
                priority = original_params['priority']
                action_info = f"📄 {original_params['title']} | {req_type} | {priority}"
                return self._create_above_fold_response("SUCCESS", key_info, action_info)
            
            # Create parent requirement first
            parent_req_id = self._create_single_requirement({
                **original_params,
                "title": f"{original_params['title']} (Parent)",
                "current_state": f"Parent requirement for: {original_params['current_state']}",
                "desired_state": (f"Decomposed into {len(suggestions)} sub-requirements: "
                                 f"{original_params['desired_state']}")
            })
            
            # Create sub-requirements
            sub_req_ids = []
            for i, suggestion in enumerate(suggestions, 1):
                # Create sub-requirement with decomposed content
                sub_req_data = {
                    "type": suggestion.get("type", original_params["type"]),
                    "title": suggestion["title"],
                    "priority": original_params["priority"],  # Inherit parent priority
                    "current_state": (f"Sub-requirement {i} of {parent_req_id}: "
                                     f"{suggestion.get('current_state', original_params['current_state'])}"),
                    "desired_state": suggestion.get("desired_state", suggestion["title"]),
                    "business_value": f"Supports {parent_req_id}: {suggestion.get('rationale', '')}",
                    "author": original_params.get("author", "MCP User"),
                    "risk_level": original_params.get("risk_level", "Medium"),
                    "functional_requirements": original_params.get("functional_requirements", []),
                    "acceptance_criteria": original_params.get("acceptance_criteria", [])
                }
                
                sub_req_id = self._create_single_requirement(sub_req_data)
                sub_req_ids.append(sub_req_id)
                
                # Create parent-child relationship
                self._create_requirement_dependency(sub_req_id, parent_req_id, "parent")
            
            # Build comprehensive response
            response = f"""# Automatic Requirement Decomposition Complete

## Parent Requirement Created
- **{parent_req_id}**: {original_params['title']} (Parent)

## Sub-Requirements Created ({len(sub_req_ids)})
"""
            for i, (sub_req_id, suggestion) in enumerate(zip(sub_req_ids, suggestions), 1):
                req_type = suggestion.get('type', original_params['type'])
                response += f"{i}. **{sub_req_id}**: {suggestion['title']} ({req_type})\n"
                response += f"   - Rationale: {suggestion.get('rationale', 'N/A')}\n"
            
            response += f"""
## Decomposition Analysis
- **Complexity Score**: {analysis.get('analysis', {}).get('complexity_score', 'N/A')}/10
- **Scope Assessment**: {analysis.get('analysis', {}).get('scope_assessment', 'N/A')}
- **Implementation Focus**: {analysis.get('analysis', {}).get('implementation_focus', 'N/A')}

## Next Steps
- Use `trace_requirement` on {parent_req_id} to see full decomposition
- Create tasks for individual sub-requirements
- Each sub-requirement can be implemented independently
"""
            
            # Create above-the-fold response
            key_info = f"Requirement decomposed into {len(sub_req_ids)} sub-requirements"
            action_info = f"🔄 Parent: {parent_req_id} | {len(sub_req_ids)} children created"
            return self._create_above_fold_response("SUCCESS", key_info, action_info, response)
            
        except Exception as e:
            # Fallback to single requirement creation if decomposition fails
            self.logger.warning(f"Automatic decomposition failed, creating single requirement: {e}")
            req_id = self._create_single_requirement(original_params)
            key_info = f"Requirement {req_id} created"
            action_info = f"📄 {original_params['title']} | Decomposition failed, created single requirement"
            return self._create_above_fold_response("SUCCESS", key_info, action_info)
    
    def _create_requirement_dependency(self, requirement_id: str, depends_on_id: str, dependency_type: str):
        """Create a requirement dependency relationship"""
        try:
            self.db.insert_record("requirement_dependencies", {
                "requirement_id": requirement_id,
                "depends_on_requirement_id": depends_on_id,
                "dependency_type": dependency_type
            })
            self._log_operation(
                "requirement_dependency", requirement_id, 
                f"created_{dependency_type}_relationship", f"Linked to {depends_on_id}"
            )
        except Exception as e:
            self.logger.error(f"Failed to create requirement dependency: {e}")
    
    async def _update_requirement_status(self, **params) -> List[TextContent]:
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
            
            # Validate task completion before allowing Validated status
            if new_status == "Validated":
                incomplete_tasks = self.db.execute_query("""
                    SELECT t.id, t.title, t.status FROM tasks t
                    JOIN requirement_tasks rt ON t.id = rt.task_id
                    WHERE rt.requirement_id = ? AND t.status != 'Complete'
                """, [params["requirement_id"]], fetch_all=True, row_factory=True)
                
                if incomplete_tasks:
                    task_list = "\n".join(f"- {task['id']}: {task['title']} (status: {task['status']})" 
                                        for task in incomplete_tasks)
                    error_msg = (f"Cannot validate requirement with incomplete tasks. "
                               f"The following tasks must be completed first:\n{task_list}\n\n"
                               f"All tasks must have 'Complete' status before requirement validation.")
                    return self._create_error_response(error_msg)
            
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
            
            # Create above-the-fold response
            key_info = f"Requirement {params['requirement_id']} updated"
            action_info = f"📈 {current_status} → {new_status}"
            
            return self._create_above_fold_response("SUCCESS", key_info, action_info)
            
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
                return self._create_above_fold_response(
                    "INFO", "No requirements found", "Try adjusting search criteria"
                )
            
            # Build filter description for above-the-fold
            filters = []
            if params.get("status"):
                filters.append(f"status: {params['status']}")
            if params.get("priority"):
                filters.append(f"priority: {params['priority']}")
            if params.get("type"):
                filters.append(f"type: {params['type']}")
            if params.get("search_text"):
                filters.append(f"search: {params['search_text']}")
            filter_desc = " | ".join(filters) if filters else "all requirements"
            
            # Build detailed list
            req_list = []
            for req in requirements:
                req_info = f"- {req['id']}: {req['title']} [{req['status']}] {req['priority']}"
                req_list.append(req_info)
            
            key_info = self._format_count_summary("requirement", len(requirements), filter_desc)
            details = "\n".join(req_list)
            
            return self._create_above_fold_response("SUCCESS", key_info, "", details)
            
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
            
            # Create above-the-fold response for requirement details
            key_info = f"Requirement {req['id']} details"
            action_info = f"📄 {req['title']} | {req['status']} | {req['priority']}"
            return self._create_above_fold_response("INFO", key_info, action_info, report)
            
        except Exception as e:
            return self._create_error_response("Failed to get requirement details", e)
    
    def _trace_requirement(self, **params) -> List[TextContent]:
        """Trace requirement through full lifecycle including decomposition relationships"""
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
            
            # Get parent requirements (if this is a child requirement)
            parent_requirements = self.db.execute_query("""
                SELECT r.* FROM requirements r
                JOIN requirement_dependencies rd ON r.id = rd.depends_on_requirement_id
                WHERE rd.requirement_id = ? AND rd.dependency_type = 'parent'
            """, [params["requirement_id"]], fetch_all=True, row_factory=True)
            
            # Get child requirements (if this is a parent requirement)
            child_requirements = self.db.execute_query("""
                SELECT r.* FROM requirements r
                JOIN requirement_dependencies rd ON r.id = rd.requirement_id
                WHERE rd.depends_on_requirement_id = ? AND rd.dependency_type = 'parent'
                ORDER BY r.created_at
            """, [params["requirement_id"]], fetch_all=True, row_factory=True)
            
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
"""
            
            # Add decomposition relationships if they exist
            if parent_requirements:
                report += f"\n## Parent Requirements ({len(parent_requirements)})\n"
                for parent in parent_requirements:
                    report += f"- {parent['id']}: {parent['title']} [{parent['status']}]\n"
                    report += f"  Created: {parent['created_at']}\n"
            
            if child_requirements:
                report += f"\n## Child Requirements ({len(child_requirements)})\n"
                for i, child in enumerate(child_requirements, 1):
                    report += f"{i}. {child['id']}: {child['title']} [{child['status']}]\n"
                    progress = f"{child['tasks_completed']}/{child['task_count']}"
                    report += f"   Priority: {child['priority']} | Progress: {progress} tasks\n"
                
                # Calculate overall decomposition progress
                if child_requirements:
                    total_child_tasks = sum(child['task_count'] for child in child_requirements)
                    completed_child_tasks = sum(child['tasks_completed'] for child in child_requirements)
                    decomp_progress = (completed_child_tasks / total_child_tasks * 100) if total_child_tasks > 0 else 0
                    progress_text = f"{completed_child_tasks}/{total_child_tasks}"
                    report += f"\n**Overall Decomposition Progress**: {progress_text} tasks ({decomp_progress:.1f}%)\n"

            report += f"\n## Implementation Tasks ({len(tasks)})\n"
            for task in tasks:
                report += f"- {task['id']}: {task['title']} [{task['status']}]"
                if task['assignee']:
                    report += f" (Assigned: {task['assignee']})"
                report += "\n"
            
            if architecture:
                report += f"\n## Architecture Decisions ({len(architecture)})\n"
                for arch in architecture:
                    report += f"- {arch['id']}: {arch['title']} [{arch['status']}]\n"
            
            # Create above-the-fold response for requirement trace
            key_info = f"Requirement {req['id']} trace"
            decomp_info = ""
            if parent_requirements:
                decomp_info = f" | Child of {len(parent_requirements)} parent(s)"
            elif child_requirements:
                decomp_info = f" | Parent to {len(child_requirements)} children"
            
            arch_count = len(architecture) if architecture else 0
            action_info = f"🔍 {req['title']} | {len(tasks)} tasks | {arch_count} architecture{decomp_info}"
            return self._create_above_fold_response("INFO", key_info, action_info, report)
            
        except Exception as e:
            return self._create_error_response("Failed to trace requirement", e)