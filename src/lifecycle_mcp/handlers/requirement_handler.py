#!/usr/bin/env python3
"""
Requirement Handler for MCP Lifecycle Management Server
Handles all requirement-related operations
"""

import json
from collections import deque
from collections.abc import Iterable
from typing import Any

from mcp.types import TextContent

from ..database_manager import DatabaseManager
from ..rules import thin_record_reasons
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

# Records that depend on a requirement and therefore block deleting it.
REQUIREMENT_DELETE_BLOCKERS = [
    (
        "tasks",
        "SELECT target_id FROM relationships WHERE source_type = 'requirement' AND source_id = ? "
        "AND target_type = 'task' AND relationship_type = 'implements'",
    ),
    (
        "architecture decisions",
        "SELECT target_id FROM relationships WHERE source_type = 'requirement' AND source_id = ? "
        "AND target_type = 'architecture' AND relationship_type = 'addresses'",
    ),
    (
        "requirements linking to it",
        "SELECT source_id FROM relationships WHERE target_type = 'requirement' AND target_id = ? "
        "AND source_type = 'requirement'",
    ),
]


# Fields update_requirement can change. The type is part of the ID; status moves go through update_requirement_status.
REQUIREMENT_EDITABLE = (
    "title",
    "priority",
    "risk_level",
    "current_state",
    "desired_state",
    "functional_requirements",
    "acceptance_criteria",
    "business_value",
    "nonfunctional_requirements",
    "technical_constraints",
    "business_rules",
    "validation_metrics",
    "out_of_scope",
)
# Curated list fields (roadmap R6b), shown after the acceptance criteria in details and export: (column, title).
REQUIREMENT_LIST_SECTIONS = (
    ("nonfunctional_requirements", "Non-Functional Requirements"),
    ("technical_constraints", "Technical Constraints"),
    ("business_rules", "Business Rules"),
    ("validation_metrics", "Validation Metrics"),
    ("out_of_scope", "Out of Scope"),
)
REQUIREMENT_JSON_FIELDS = (
    "functional_requirements",
    "acceptance_criteria",
    *(column for column, _ in REQUIREMENT_LIST_SECTIONS),
)

# A requirement in one of these statuses has been approved: edits need a reason and flag it as changed since review.
REVIEWED_STATUSES = ("Approved", "Architecture", "Ready", "Implemented", "Validated", "Deprecated")

# Status -> the statuses update_requirement_status may move a requirement to next.
REQUIREMENT_TRANSITIONS = {
    "Draft": ["Under Review", "Deprecated"],
    "Under Review": ["Draft", "Approved", "Deprecated"],
    "Approved": ["Architecture", "Ready", "Deprecated"],
    "Architecture": ["Ready", "Approved"],
    "Ready": ["Implemented", "Deprecated"],
    "Implemented": ["Validated", "Ready"],
    "Validated": ["Deprecated"],
    "Deprecated": [],
}
# The tasks implementing a requirement that are not Complete, for the Implemented gate (roadmap R8).
OPEN_TASKS_SQL = """
    SELECT t.id, t.status FROM tasks t JOIN relationships rel ON rel.target_id = t.id
    WHERE rel.source_type = 'requirement' AND rel.source_id = ?
      AND rel.target_type = 'task' AND rel.relationship_type = 'implements' AND t.status != 'Complete'
    ORDER BY t.id
"""

# A multi-step move may end at these statuses but never pass through them: tasks and ADRs are planned against an
# approved requirement, and validation is a deliberate step (ADR-0003).
REQUIREMENT_STOP_STATUSES = ("Approved", "Validated")


def requirement_path(current: str, target: str, stops: Iterable[str] = REQUIREMENT_STOP_STATUSES) -> list[str] | None:
    """The shortest allowed sequence of statuses from current to target that passes through none of stops"""
    if target == current:
        return None
    paths, seen = deque([[current]]), {current}
    while paths:
        path = paths.popleft()
        for status in REQUIREMENT_TRANSITIONS.get(path[-1], []):
            if status == target:
                return [*path, status]
            if status not in seen and status not in stops:
                seen.add(status)
                paths.append([*path, status])
    return None


def refused_move_reason(current: str, target: str) -> str:
    """Why update_requirement_status can't move a requirement from current to target, and what it can do instead"""
    detour = requirement_path(current, target, stops=())
    if detour:
        stop = next(status for status in detour[1:-1] if status in REQUIREMENT_STOP_STATUSES)
        return (
            f"Invalid transition from {current} to {target} in one call: it would pass through {stop}. "
            f"Move it to {stop} first"
        )
    allowed = ", ".join(REQUIREMENT_TRANSITIONS.get(current, [])) or "nothing"
    return f"Invalid transition from {current} to {target}. From {current} it can move to: {allowed}"


# Content edits to reviewed requirements made after their latest status change. The marker is derived rather than
# stored: the next status transition clears it, and that transition's comment serves as the acknowledgement.
CHANGES_SINCE_REVIEW_SQL = """
    SELECT e.entity_id, r.title, r.status, e.field FROM lifecycle_events e
    JOIN requirements r ON r.id = e.entity_id
    WHERE e.entity_type = 'requirement' AND e.event_type = 'field_edit'
      AND r.status IN (SELECT value FROM json_each(?))
      AND e.id > COALESCE((
          SELECT MAX(s.id) FROM lifecycle_events s
          WHERE s.entity_type = 'requirement' AND s.entity_id = e.entity_id AND s.event_type = 'status_change'
      ), 0)
"""


# When a requirement was last checked against reality, and when its content last changed. Verification is a comment
# or a status move: someone looked at it and said something. Both are derived from what is already recorded, the way
# changes_since_review is, so there is no column to keep in step (roadmap R11).
#
# Unlike changes_since_review this covers every status, including Draft: a requirement written once and never
# re-checked is exactly the case that goes stale, and six did in this project before anyone noticed.
# Times here are second-resolution, so an edit and a check in the same second compare equal. Within lifecycle_events
# the row id settles the order, the way changes_since_review already uses it; comments live in another table, so a
# comment in the same second as an edit counts as checking it.
LAST_VERIFIED_SQL = """
    SELECT r.id, r.title, r.status,
        (SELECT MAX(e.id) FROM lifecycle_events e
         WHERE e.entity_type = 'requirement' AND e.entity_id = r.id AND e.event_type = 'status_change') AS moved_event,
        (SELECT MAX(occurred_at) FROM lifecycle_events e
         WHERE e.entity_type = 'requirement' AND e.entity_id = r.id AND e.event_type = 'status_change') AS moved_at,
        (SELECT MAX(created_at) FROM reviews v
         WHERE v.entity_type = 'requirement' AND v.entity_id = r.id) AS commented_at,
        (SELECT MAX(e.id) FROM lifecycle_events e
         WHERE e.entity_type = 'requirement' AND e.entity_id = r.id
           AND e.event_type IN ('field_edit', 'created')) AS changed_event,
        (SELECT MAX(occurred_at) FROM lifecycle_events e
         WHERE e.entity_type = 'requirement' AND e.entity_id = r.id
           AND e.event_type IN ('field_edit', 'created')) AS changed_at
    FROM requirements r
    WHERE r.status != 'Deprecated'
"""


def verification(db: DatabaseManager, requirement_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Each requirement's last verification and last content change: ID -> title, status, verified_at, changed_at.

    verified_at is None when nobody has commented on it or moved it since it was written. A requirement is stale
    when its content changed after that, which stale_requirements() reports.
    """
    sql, params = LAST_VERIFIED_SQL, []
    if requirement_id:
        sql, params = sql + " AND r.id = ?", [requirement_id]
    records: dict[str, dict[str, Any]] = {}
    for row in db.execute_query(sql, params, fetch_all=True, row_factory=True) or []:
        verified_at = max(filter(None, (row["moved_at"], row["commented_at"])), default=None)
        # Changed since it was checked? Against a status move the event ids settle it, even within one second.
        # Against a comment only the times compare, and a comment in the same second counts as checking it.
        moved_after = row["moved_event"] is not None and row["moved_event"] > (row["changed_event"] or 0)
        commented_after = row["commented_at"] is not None and row["commented_at"] >= (row["changed_at"] or "")
        records[row["id"]] = {
            "title": row["title"],
            "status": row["status"],
            "verified_at": verified_at,
            "changed_at": row["changed_at"],
            "verified_since_change": bool(moved_after or commented_after),
        }
    return records


def stale_requirements(db: DatabaseManager) -> dict[str, dict[str, Any]]:
    """Requirements whose content changed after anyone last checked them, newest change first (roadmap R11)."""
    stale = {
        req_id: entry
        for req_id, entry in verification(db).items()
        if entry["changed_at"] and not entry["verified_since_change"]
    }
    return dict(sorted(stale.items(), key=lambda item: item[1]["changed_at"], reverse=True))


def changes_since_review(db: DatabaseManager, requirement_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Reviewed requirements edited since their latest status change: ID -> title, status and edited fields.

    Pass requirement_id to look at a single requirement.
    """
    sql, params = CHANGES_SINCE_REVIEW_SQL, [json.dumps(REVIEWED_STATUSES)]
    if requirement_id:
        sql, params = sql + " AND e.entity_id = ?", [*params, requirement_id]
    changed: dict[str, dict[str, Any]] = {}
    for row in db.execute_query(sql + " ORDER BY e.id", params, fetch_all=True, row_factory=True) or []:
        entry = changed.setdefault(row["entity_id"], {"title": row["title"], "status": row["status"], "fields": []})
        if row["field"] not in entry["fields"]:
            entry["fields"].append(row["field"])
    return changed


class RequirementHandler(BaseHandler):
    """Handler for requirement-related MCP tools"""

    def __init__(self, db_manager, mcp_client=None):
        """Initialize handler with database manager and optional MCP client"""
        super().__init__(db_manager)
        self.mcp_client = mcp_client

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return requirement tool definitions"""
        return [
            {
                "name": "create_requirement",
                "description": "Create a new requirement",
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
                        "author": {"type": "string"},
                        "nonfunctional_requirements": {"type": "array", "items": {"type": "string"}},
                        "technical_constraints": {"type": "array", "items": {"type": "string"}},
                        "business_rules": {"type": "array", "items": {"type": "string"}},
                        "validation_metrics": {"type": "array", "items": {"type": "string"}},
                        "out_of_scope": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["type", "title", "priority", "current_state", "desired_state"],
                },
            },
            {
                "name": "update_requirement_status",
                "description": (
                    "Move requirements through lifecycle states; walks the allowed path, "
                    "never through Approved or Validated"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"},
                        "requirement_ids": STATUS_ID_LIST_PROPERTY,
                        "new_status": {
                            "type": "string",
                            "enum": [
                                "Draft",
                                "Under Review",
                                "Approved",
                                "Architecture",
                                "Ready",
                                "Implemented",
                                "Validated",
                                "Deprecated",
                            ],
                        },
                        "comment": {"type": "string"},
                    },
                    "required": ["new_status"],
                },
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
                        "search_text": {"type": "string"},
                    },
                },
            },
            {
                "name": "trace_requirement",
                "description": "Trace requirement through implementation",
                "inputSchema": {
                    "type": "object",
                    "properties": {"requirement_id": {"type": "string"}},
                    "required": ["requirement_id"],
                },
            },
            {
                "name": "update_requirement",
                "description": (
                    "Edit content in place. At Approved or later a reason is required, and the requirement is "
                    "flagged changed since last review until its next status change."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"},
                        "title": {"type": "string"},
                        "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                        "risk_level": {"type": "string", "enum": ["High", "Medium", "Low"]},
                        "current_state": {"type": "string"},
                        "desired_state": {"type": "string"},
                        "functional_requirements": {"type": "array", "items": {"type": "string"}},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "business_value": {"type": "string"},
                        "nonfunctional_requirements": {"type": "array", "items": {"type": "string"}},
                        "technical_constraints": {"type": "array", "items": {"type": "string"}},
                        "business_rules": {"type": "array", "items": {"type": "string"}},
                        "validation_metrics": {"type": "array", "items": {"type": "string"}},
                        "out_of_scope": {"type": "array", "items": {"type": "string"}},
                        **EDIT_OPTION_PROPERTIES,
                        "reason": {"type": "string", "description": "Required at Approved or later"},
                    },
                    "required": ["requirement_id"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_requirement":
                return await self._create_requirement(**arguments)
            elif tool_name == "update_requirement_status":
                return await self._update_requirement_status(**arguments)
            elif tool_name == "query_requirements":
                return self._query_requirements(**arguments)
            elif tool_name == "trace_requirement":
                return self._trace_requirement(**arguments)
            elif tool_name == "update_requirement":
                return self._update_requirement(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    def _delete_requirement(self, **params) -> list[TextContent]:
        """Delete a Draft requirement that nothing depends on"""
        error = self._validate_required_params(params, ["requirement_id"])
        if error:
            return self._create_error_response(error)
        requirement_id = params["requirement_id"]
        try:
            removed = self._delete_entity(
                "requirements",
                "requirement",
                requirement_id,
                deletable_status="Draft",
                blockers=REQUIREMENT_DELETE_BLOCKERS,
            )
        except (LookupError, DeleteRefused) as e:
            return self._create_error_response(str(e))
        return self._create_above_fold_response(
            "SUCCESS", f"Requirement {requirement_id} deleted", f"🗑️ Removed {removed} link(s) it owned"
        )

    def _update_requirement(self, **params) -> list[TextContent]:
        """Edit requirement content; approved requirements need a reason and show as changed since last review"""
        error = self._validate_required_params(params, ["requirement_id"])
        if error:
            return self._create_error_response(error)
        requirement_id = params["requirement_id"]
        changes = {name: params[name] for name in REQUIREMENT_EDITABLE if name in params}
        if not changes:
            return self._create_error_response(
                f"Nothing to update: pass at least one of {', '.join(REQUIREMENT_EDITABLE)}"
            )
        reason = (params.get("reason") or "").strip() or None

        def require_reason_once_approved(before: dict[str, Any]) -> None:
            if before["status"] in REVIEWED_STATUSES and not reason:
                raise EditRefused(
                    f"Requirement {requirement_id} is {before['status']}; a reason is required to edit a requirement "
                    "at Approved or later. Pass reason explaining the change."
                )

        try:
            result = self._apply_edit(
                "requirements",
                "requirement",
                requirement_id,
                changes,
                editable=REQUIREMENT_EDITABLE,
                json_fields=REQUIREMENT_JSON_FIELDS,
                actor=params.get("actor") or "MCP User",
                reason=reason,
                if_revision=params.get("if_revision"),
                check=require_reason_once_approved,
            )
        except (LookupError, RevisionConflict, EditRefused) as e:
            return self._create_error_response(str(e))

        action_info = self._describe_edit(result)
        status = result.before["status"]
        flagged = bool(result.changed) and status in REVIEWED_STATUSES
        if flagged:
            action_info += f" | ⚠️ changed since last review ({status}) until its next status change"
        structured = {
            "id": requirement_id,
            "changed": result.changed,
            "revision": result.revision,
            "changed_since_review": flagged,
        }
        return self._create_structured_response(
            "SUCCESS", f"Requirement {requirement_id} updated", structured, action_info
        )

    def _last_verified_line(self, requirement_id: str) -> str:
        """Report line saying when this requirement was last checked against reality (roadmap R11)"""
        entry = verification(self.db, requirement_id).get(requirement_id)
        if not entry:
            return ""
        if not entry["verified_at"]:
            return "\n- **⚠️ Never verified**: nobody has commented on this or moved it since it was written"
        stale = entry["changed_at"] and not entry["verified_since_change"]
        marker = "⚠️ Stale since" if stale else "Last Verified"
        line = f"\n- **{marker}**: {entry['verified_at']}"
        if stale:
            line += f" (content changed at {entry['changed_at']}; a comment or status change marks it checked)"
        return line

    def _changed_since_review_line(self, requirement_id: str) -> str:
        """Report line flagging edits made since the latest status change, or "" when there are none"""
        entry = changes_since_review(self.db, requirement_id).get(requirement_id)
        if not entry:
            return ""
        return (
            f"\n- **⚠️ Changed Since Last Review**: {', '.join(entry['fields'])} edited at {entry['status']} "
            "(get_entity_history shows before, after and reason; the next status change clears this)"
        )

    async def _create_requirement(self, **params) -> list[TextContent]:
        """Create a new requirement with LLM-enhanced analysis"""
        # Validate required parameters
        error = self._validate_required_params(params, ["type", "title", "priority", "current_state", "desired_state"])
        if error:
            return self._create_error_response(error)

        # Thin for its kind? The workflow rules decide: warn and carry on, refuse, or say nothing (roadmap R11).
        try:
            warnings = self._rule_warnings(thin_record_reasons(params, "requirement"))
        except StatusRefused as e:
            return self._create_error_response(str(e))

        try:
            # Perform LLM analysis for requirement decomposition
            llm_analysis = await self._analyze_requirement_with_llm(params)

            # Handle LLM analysis results
            if llm_analysis:
                if llm_analysis.get("recommendation") == "needs_clarification":
                    # Return clarifying questions to user
                    return self._create_clarification_response(llm_analysis)
                elif llm_analysis.get("recommendation") == "decompose":
                    # Automatically create decomposed requirements
                    return await self._create_decomposed_requirements(llm_analysis, params)

            # Standard requirement creation (single requirement)
            req_id = self._create_single_requirement(params)

            # One status line; the facts an agent needs next come back as structured data (roadmap R10).
            structured = {
                "id": req_id,
                "type": params["type"],
                "title": params["title"],
                "priority": params["priority"],
                "status": "Draft",
            }
            if warnings:
                structured["warnings"] = warnings
            details = "\n".join(f"⚠️ {warning}" for warning in warnings)
            return self._create_structured_response("SUCCESS", f"Requirement {req_id} created", structured, "", details)

        except Exception as e:
            return self._create_error_response("Failed to create requirement", e)

    async def _analyze_requirement_with_llm(self, params: dict[str, Any]) -> dict[str, Any] | None:
        """Analyze requirement using LLM sampling for decomposition"""
        # Skip LLM analysis in test environments
        if hasattr(self, "_testing_mode") and self._testing_mode:
            return None

        if not self.mcp_client:
            self.logger.info("No MCP client available for sampling - using fallback requirement creation")
            return None

        try:
            # Build context for LLM analysis
            requirement_context = self._build_requirement_context(params)

            # Prepare LLM sampling request
            sampling_request = {
                "messages": [{"role": "user", "content": {"type": "text", "text": requirement_context}}],
                "modelPreferences": {"intelligencePriority": 0.8, "speedPriority": 0.2, "costPriority": 0.1},
                "systemPrompt": self._get_analysis_system_prompt(),
                "includeContext": "thisServer",
                "temperature": 0.1,
                "maxTokens": 1000,
                "stopSequences": ["```"],
            }

            # Check if the MCP client has sampling capability
            if hasattr(self.mcp_client, "sample") and callable(self.mcp_client.sample):
                try:
                    # Make the actual MCP sampling request
                    response = await self.mcp_client.sample(sampling_request)
                    if response and hasattr(response, "content") and hasattr(response.content, "text"):
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

    def _build_requirement_context(self, params: dict[str, Any]) -> str:
        """Build context string for LLM analysis"""
        context = f"""Analyze this requirement for decomposition and clarity:

Title: {params["title"]}
Type: {params["type"]}
Priority: {params["priority"]}
Current State: {params["current_state"]}
Desired State: {params["desired_state"]}
Business Value: {params.get("business_value", "Not specified")}

Functional Requirements:
{self._format_list(params.get("functional_requirements", []))}

Acceptance Criteria:
{self._format_list(params.get("acceptance_criteria", []))}

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

    def _format_list(self, items: list[str]) -> str:
        """Format list items for context"""
        if not items:
            return "- None specified"
        return "\n".join(f"- {item}" for item in items)

    def _create_clarification_response(self, analysis: dict[str, Any]) -> list[TextContent]:
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
        self, analysis: dict[str, Any], original_params: dict[str, Any]
    ) -> list[TextContent]:
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

    def _create_single_requirement(self, params: dict[str, Any]) -> str:
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
            "risk_level": params.get("risk_level", "Medium"),
            **{
                column: self._safe_json_dumps(params[column])
                for column, _ in REQUIREMENT_LIST_SECTIONS
                if column in params
            },
        }

        # Insert requirement
        self.db.insert_record("requirements", req_data)

        # Log event
        self._log_operation("requirement", req_id, "created", params.get("author", "MCP User"))

        return req_id

    async def _create_decomposed_requirements(
        self, analysis: dict[str, Any], original_params: dict[str, Any]
    ) -> list[TextContent]:
        """Create decomposed sub-requirements automatically from LLM analysis"""
        try:
            suggestions = analysis.get("decomposition", {}).get("suggested_sub_requirements", [])

            if not suggestions:
                # Fallback to single requirement if no suggestions
                req_id = self._create_single_requirement(original_params)
                key_info = f"Requirement {req_id} created"
                req_type = original_params["type"]
                priority = original_params["priority"]
                action_info = f"📄 {original_params['title']} | {req_type} | {priority}"
                return self._create_above_fold_response("SUCCESS", key_info, action_info)

            # Create parent requirement first
            parent_req_id = self._create_single_requirement(
                {
                    **original_params,
                    "title": f"{original_params['title']} (Parent)",
                    "current_state": f"Parent requirement for: {original_params['current_state']}",
                    "desired_state": (
                        f"Decomposed into {len(suggestions)} sub-requirements: {original_params['desired_state']}"
                    ),
                }
            )

            # Create sub-requirements
            sub_req_ids = []
            for i, suggestion in enumerate(suggestions, 1):
                # Create sub-requirement with decomposed content
                sub_req_data = {
                    "type": suggestion.get("type", original_params["type"]),
                    "title": suggestion["title"],
                    "priority": original_params["priority"],  # Inherit parent priority
                    "current_state": (
                        f"Sub-requirement {i} of {parent_req_id}: "
                        f"{suggestion.get('current_state', original_params['current_state'])}"
                    ),
                    "desired_state": suggestion.get("desired_state", suggestion["title"]),
                    "business_value": f"Supports {parent_req_id}: {suggestion.get('rationale', '')}",
                    "author": original_params.get("author", "MCP User"),
                    "risk_level": original_params.get("risk_level", "Medium"),
                    "functional_requirements": original_params.get("functional_requirements", []),
                    "acceptance_criteria": original_params.get("acceptance_criteria", []),
                }

                sub_req_id = self._create_single_requirement(sub_req_data)
                sub_req_ids.append(sub_req_id)

                # Create parent-child relationship
                self._create_requirement_dependency(sub_req_id, parent_req_id, "parent")

            # Build comprehensive response
            response = f"""# Automatic Requirement Decomposition Complete

## Parent Requirement Created
- **{parent_req_id}**: {original_params["title"]} (Parent)

## Sub-Requirements Created ({len(sub_req_ids)})
"""
            for i, (sub_req_id, suggestion) in enumerate(zip(sub_req_ids, suggestions, strict=False), 1):
                req_type = suggestion.get("type", original_params["type"])
                response += f"{i}. **{sub_req_id}**: {suggestion['title']} ({req_type})\n"
                response += f"   - Rationale: {suggestion.get('rationale', 'N/A')}\n"

            response += f"""
## Decomposition Analysis
- **Complexity Score**: {analysis.get("analysis", {}).get("complexity_score", "N/A")}/10
- **Scope Assessment**: {analysis.get("analysis", {}).get("scope_assessment", "N/A")}
- **Implementation Focus**: {analysis.get("analysis", {}).get("implementation_focus", "N/A")}

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
            self._link("requirement", requirement_id, "requirement", depends_on_id, dependency_type)
            self._log_operation(
                "requirement_dependency",
                requirement_id,
                f"created_{dependency_type}_relationship",
                f"Linked to {depends_on_id}",
            )
        except Exception as e:
            self.logger.error(f"Failed to create requirement dependency: {e}")

    async def _update_requirement_status(self, **params) -> list[TextContent]:
        """Move one requirement, or each of requirement_ids, to new_status (roadmap R9)"""
        error = self._validate_required_params(params, ["new_status"])
        if error:
            return self._create_error_response(error)
        return await self._change_statuses(
            params,
            "requirement_id",
            "Requirement",
            "requirements",
            lambda requirement_id: self._change_requirement_status(requirement_id, params),
            "Failed to update requirement status",
        )

    async def _change_requirement_status(self, requirement_id: str, params: dict[str, Any]) -> StatusChange:
        """Move one requirement to new_status; raises StatusRefused when it is missing or the move isn't allowed"""
        current_req = self.db.get_records("requirements", "status", "id = ?", [requirement_id])
        if not current_req:
            raise StatusRefused("Requirement not found")

        current_status = current_req[0]["status"]
        new_status = params["new_status"]
        path = requirement_path(current_status, new_status)
        if path is None:
            raise StatusRefused(refused_move_reason(current_status, new_status))

        # Validate task completion before allowing Validated status
        if new_status == "Validated":
            incomplete_tasks = self.db.execute_query(
                """
                SELECT t.id, t.title, t.status FROM tasks t
                JOIN relationships rel ON rel.target_id = t.id
                WHERE rel.source_type = 'requirement' AND rel.source_id = ?
                  AND rel.target_type = 'task' AND rel.relationship_type = 'implements'
                  AND t.status != 'Complete'
            """,
                [requirement_id],
                fetch_all=True,
                row_factory=True,
            )

            if incomplete_tasks:
                task_list = "\n".join(
                    f"- {task['id']}: {task['title']} (status: {task['status']})" for task in incomplete_tasks
                )
                raise StatusRefused(
                    f"Cannot validate requirement with incomplete tasks. "
                    f"The following tasks must be completed first:\n{task_list}\n\n"
                    f"All tasks must have 'Complete' status before requirement validation."
                )

        # Reaching Implemented with open tasks is a workflow rule: warn or enforce, unlike the Validated gate
        # above, which is always on (roadmap R8, ADR-0004).
        warnings = self._rule_warnings(self._implemented_gate_reasons(requirement_id, path))

        # One UPDATE per step, so the status trigger logs each step; all of them or none (ADR-0003).
        # CURRENT_TIMESTAMP has to be SQL, not a bound value (F-42).
        with self.db.transaction() as cur:
            for status in path[1:]:
                cur.execute(
                    "UPDATE requirements SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [status, requirement_id],
                )
            if params.get("comment"):
                cur.execute(
                    "INSERT INTO reviews (entity_type, entity_id, reviewer, comment) VALUES ('requirement', ?, ?, ?)",
                    [requirement_id, "MCP User", params["comment"]],
                )

        return StatusChange(
            requirement_id, current_status, new_status, path if len(path) > 2 else None, warnings=warnings
        )

    def _implemented_gate_reasons(self, requirement_id: str, path: list[str]) -> list[str]:
        """Why reaching Implemented is risky: tasks implementing the requirement are still open (roadmap R8)"""
        if "Implemented" not in path[1:]:
            return []
        rows = self.db.execute_query(OPEN_TASKS_SQL, [requirement_id], fetch_all=True, row_factory=True) or []
        if not rows:
            return []
        listed = ", ".join(f"{row['id']} ({row['status']})" for row in rows)
        return [f"Tasks not Complete: {listed}"]

    def _query_requirements(self, **params) -> list[TextContent]:
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
                "requirements", "*", where_clause, where_params, "priority, created_at DESC"
            )
            # The full records, JSON fields parsed, as structured data next to the list (roadmap R10)
            structured = {
                "requirements": self._record_dicts(requirements, REQUIREMENT_JSON_FIELDS),
                "count": len(requirements),
            }

            if not requirements:
                return self._create_structured_response(
                    "INFO", "No requirements found", structured, "Try adjusting search criteria"
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

            return self._create_structured_response("SUCCESS", key_info, structured, "", details)

        except Exception as e:
            return self._create_error_response("Failed to query requirements", e)

    def _get_requirement_details(self, **params) -> list[TextContent]:
        """Get full requirement details"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_id"])
        if error:
            return self._create_error_response(error)

        try:
            # Get requirement
            requirements = self.db.get_records("requirements", "*", "id = ?", [params["requirement_id"]])

            if not requirements:
                return self._create_error_response("Requirement not found")

            req = requirements[0]
            review_line = self._changed_since_review_line(req["id"])
            verified_line = self._last_verified_line(req["id"])

            # Build detailed report
            report = f"""# Requirement Details: {req["id"]}

## Basic Information
- **Title**: {req["title"]}
- **Type**: {req["type"]}
- **Status**: {req["status"]}
- **Priority**: {req["priority"]}
- **Risk Level**: {req["risk_level"]}
- **Author**: {req["author"]}
- **Created**: {req["created_at"]}
- **Updated**: {req["updated_at"]}
- **Revision**: {req["revision"]}{verified_line}{review_line}

## Problem Definition
**Current State**: {req["current_state"]}

**Desired State**: {req["desired_state"]}

**Business Value**: {req["business_value"] or "Not specified"}

## Requirements Details
"""

            if req["functional_requirements"]:
                func_reqs = self._safe_json_loads(req["functional_requirements"])
                if func_reqs:
                    report += "### Functional Requirements\n"
                    for fr in func_reqs:
                        report += f"- {fr}\n"

            if req["acceptance_criteria"]:
                acc_criteria = self._safe_json_loads(req["acceptance_criteria"])
                if acc_criteria:
                    report += "\n### Acceptance Criteria\n"
                    for ac in acc_criteria:
                        report += f"- {ac}\n"

            report += self._format_sections(req, REQUIREMENT_LIST_SECTIONS, "\n### {title}\n{body}")

            # Get linked tasks
            tasks = self.db.execute_query(
                """
                SELECT t.* FROM tasks t
                JOIN relationships rel ON rel.target_id = t.id
                WHERE rel.source_type = 'requirement' AND rel.source_id = ?
                  AND rel.target_type = 'task' AND rel.relationship_type = 'implements'
            """,
                [params["requirement_id"]],
                fetch_all=True,
                row_factory=True,
            )

            if tasks:
                report += f"\n## Linked Tasks ({len(tasks)})\n"
                for task in tasks:
                    report += f"- {task['id']}: {task['title']} [{task['status']}]\n"

            report += self._format_comments("requirement", req["id"])

            # Create above-the-fold response for requirement details
            key_info = f"Requirement {req['id']} details"
            action_info = f"📄 {req['title']} | {req['status']} | {req['priority']}"
            if review_line:
                action_info += " | ⚠️ changed since last review"
            return self._create_above_fold_response("INFO", key_info, action_info, report)

        except Exception as e:
            return self._create_error_response("Failed to get requirement details", e)

    def _trace_requirement(self, **params) -> list[TextContent]:
        """Trace requirement through full lifecycle including decomposition relationships"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_id"])
        if error:
            return self._create_error_response(error)

        try:
            # Get requirement
            requirements = self.db.get_records("requirements", "*", "id = ?", [params["requirement_id"]])

            if not requirements:
                return self._create_error_response("Requirement not found")

            req = requirements[0]

            # Get parent requirements (if this is a child requirement)
            parent_requirements = self.db.execute_query(
                """
                SELECT r.* FROM requirements r
                JOIN relationships rel ON rel.target_id = r.id
                WHERE rel.source_type = 'requirement' AND rel.source_id = ?
                  AND rel.target_type = 'requirement' AND rel.relationship_type = 'parent'
            """,
                [params["requirement_id"]],
                fetch_all=True,
                row_factory=True,
            )

            # Get child requirements (if this is a parent requirement)
            child_requirements = self.db.execute_query(
                """
                SELECT r.* FROM requirements r
                JOIN relationships rel ON rel.source_id = r.id
                WHERE rel.target_type = 'requirement' AND rel.target_id = ?
                  AND rel.source_type = 'requirement' AND rel.relationship_type = 'parent'
                ORDER BY r.created_at
            """,
                [params["requirement_id"]],
                fetch_all=True,
                row_factory=True,
            )

            # Get tasks
            tasks = self.db.execute_query(
                """
                SELECT t.* FROM tasks t
                JOIN relationships rel ON rel.target_id = t.id
                WHERE rel.source_type = 'requirement' AND rel.source_id = ?
                  AND rel.target_type = 'task' AND rel.relationship_type = 'implements'
                ORDER BY t.task_number, t.subtask_number
            """,
                [params["requirement_id"]],
                fetch_all=True,
                row_factory=True,
            )

            # Get architecture
            architecture = self.db.execute_query(
                """
                SELECT a.* FROM architecture a
                JOIN relationships rel ON rel.target_id = a.id
                WHERE rel.source_type = 'requirement' AND rel.source_id = ?
                  AND rel.target_type = 'architecture' AND rel.relationship_type = 'addresses'
            """,
                [params["requirement_id"]],
                fetch_all=True,
                row_factory=True,
            )

            # Build trace report
            review_line = self._changed_since_review_line(req["id"])
            report = f"""# Requirement Trace: {req["id"]}

## Requirement Details
- **Title**: {req["title"]}
- **Status**: {req["status"]}
- **Priority**: {req["priority"]}
- **Created**: {req["created_at"]}
- **Progress**: {req["tasks_completed"]}/{req["task_count"]} tasks complete{review_line}

## Current State
{req["current_state"]}

## Desired State
{req["desired_state"]}
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
                    total_child_tasks = sum(child["task_count"] for child in child_requirements)
                    completed_child_tasks = sum(child["tasks_completed"] for child in child_requirements)
                    decomp_progress = (completed_child_tasks / total_child_tasks * 100) if total_child_tasks > 0 else 0
                    progress_text = f"{completed_child_tasks}/{total_child_tasks}"
                    report += f"\n**Overall Decomposition Progress**: {progress_text} tasks ({decomp_progress:.1f}%)\n"

            report += f"\n## Implementation Tasks ({len(tasks)})\n"
            for task in tasks:
                report += f"- {task['id']}: {task['title']} [{task['status']}]"
                if task["assignee"]:
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
            if review_line:
                action_info += " | ⚠️ changed since last review"
            return self._create_above_fold_response("INFO", key_info, action_info, report)

        except Exception as e:
            return self._create_error_response("Failed to trace requirement", e)
