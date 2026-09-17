#!/usr/bin/env python3
"""
Architecture Handler for MCP Lifecycle Management Server
Handles all architecture decision-related operations
"""

from typing import Any

from mcp.types import TextContent

from ..database_manager import DatabaseManager
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

# Records that depend on an architecture decision and therefore block deleting it. The requirement links it
# addresses belong to the decision itself and are removed with it.
ARCHITECTURE_DELETE_BLOCKERS = [
    ("decisions superseded by it", "SELECT id FROM architecture WHERE superseded_by = ?"),
    (
        "other links",
        "SELECT source_id FROM relationships WHERE target_type = 'architecture' AND target_id = ? "
        "AND relationship_type != 'addresses'",
    ),
]


# update_architecture parameter -> column. Parameters are named as in create_architecture_decision.
ARCHITECTURE_EDIT_COLUMNS = {
    "title": "title",
    "context": "context",
    "decision": "decision_outcome",
    "decision_drivers": "decision_drivers",
    "considered_options": "considered_options",
    "consequences": "consequences",
    "authors": "authors",
    "deciders": "deciders",
    "implementation_notes": "implementation_notes",
    "validation_criteria": "validation_criteria",
    "risk_assessment": "risk_assessment",
}
# Curated list fields (roadmap R6b), shown after the consequences in details and export: (column, title).
ARCHITECTURE_LIST_SECTIONS = (
    ("validation_criteria", "Validation Criteria"),
    ("risk_assessment", "Risk Assessment"),
)
ARCHITECTURE_JSON_FIELDS = (
    "decision_drivers",
    "considered_options",
    "consequences",
    "authors",
    "deciders",
    *(column for column, _ in ARCHITECTURE_LIST_SECTIONS),
)
# Status -> the statuses a record usually moves to next: the ADR vocabulary, then the TDD and INTG chain. Superseded
# also needs a supersedes link (R9), which is checked whatever the workflow rules say (roadmap R8).
ARCHITECTURE_TRANSITIONS = {
    "Proposed": ["Accepted", "Rejected", "Deprecated", "Superseded"],
    "Accepted": ["Deprecated", "Superseded"],
    "Rejected": ["Proposed"],
    "Deprecated": [],
    "Superseded": [],
    "Draft": ["Under Review", "Deprecated"],
    "Under Review": ["Draft", "Approved", "Deprecated"],
    "Approved": ["Implemented", "Deprecated"],
    "Implemented": ["Deprecated", "Superseded"],
}

# Curated create/update inputs (roadmap R6b), shared by both tool schemas.
ARCHITECTURE_CURATED_PROPERTIES = {
    "deciders": {"type": "array", "items": {"type": "string"}},
    "implementation_notes": {"type": "string"},
    "validation_criteria": {"type": "array", "items": {"type": "string"}},
    "risk_assessment": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Each: risk, likelihood, impact, mitigation",
    },
}

# An amendment is a dated, attributed correction recorded against an accepted decision. It is not an edit: the
# decision's own columns are never touched, so "the original is never altered" is true of the stored row and not
# merely of the rendering. It lives as a lifecycle event because that is what it is - something that happened at a
# time, by someone, for a reason - which also gives get_entity_history its own entry for free (roadmap R20, F-51).
AMENDMENTS_SQL = """
    SELECT occurred_at, to_value, actor, reason FROM lifecycle_events
    WHERE entity_type = 'architecture' AND entity_id = ? AND event_type = 'amendment'
    ORDER BY id
"""


def amendments(db: DatabaseManager, architecture_id: str) -> list[Any]:
    """Every amendment recorded against a decision, oldest first (roadmap R20)"""
    return db.execute_query(AMENDMENTS_SQL, [architecture_id], fetch_all=True, row_factory=True) or []


def format_amendments(rows: list[Any], heading: str = "## Amendments") -> str:
    """Amendments rendered to sit with the decision they correct; "" when there are none.

    They are marked as later corrections and never merged into the decision text above them, so a reader can see
    both what was decided and what was later found to be wrong about it.
    """
    if not rows:
        return ""
    lines = ""
    for row in rows:
        by = f" by {row['actor']}" if row["actor"] else ""
        lines += f"- **{row['occurred_at']}**{by}: {row['to_value']}\n"
        if row["reason"]:
            lines += f"  Reason: {row['reason']}\n"
    return f"\n{heading} ({len(rows)})\nLater corrections; the decision above stands as it was written.\n{lines}"


class ArchitectureHandler(BaseHandler):
    """Handler for architecture decision-related MCP tools"""

    def __init__(self, db_manager):
        """Initialize handler with database manager"""
        super().__init__(db_manager)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
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
                        "authors": {"type": "array", "items": {"type": "string"}},
                        **ARCHITECTURE_CURATED_PROPERTIES,
                    },
                    "required": ["requirement_ids", "title", "context", "decision"],
                },
            },
            {
                "name": "update_architecture_status",
                "description": "Update architecture decision status; Superseded comes from a supersedes link",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "architecture_id": {"type": "string"},
                        "architecture_ids": STATUS_ID_LIST_PROPERTY,
                        "new_status": {
                            "type": "string",
                            "enum": [
                                "Proposed",
                                "Accepted",
                                "Rejected",
                                "Deprecated",
                                "Superseded",
                                "Draft",
                                "Under Review",
                                "Approved",
                                "Implemented",
                            ],
                        },
                        "comment": {"type": "string"},
                    },
                    "required": ["new_status"],
                },
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
                        "search_text": {"type": "string"},
                    },
                },
            },
            {
                "name": "update_architecture",
                "description": ("Edit while Proposed; correct an Accepted one with amendment. Otherwise supersede it."),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "architecture_id": {"type": "string"},
                        "title": {"type": "string"},
                        "context": {"type": "string"},
                        "decision": {"type": "string"},
                        "consequences": {"type": "object"},
                        "decision_drivers": {"type": "array", "items": {"type": "string"}},
                        "considered_options": {"type": "array", "items": {"type": "string"}},
                        "authors": {"type": "array", "items": {"type": "string"}},
                        **ARCHITECTURE_CURATED_PROPERTIES,
                        **EDIT_OPTION_PROPERTIES,
                        "amendment": {
                            "type": "string",
                            "description": "Dated correction to an Accepted decision; its own text stays as written",
                        },
                    },
                    "required": ["architecture_id"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "create_architecture_decision":
                return await self._create_architecture_decision(**arguments)
            elif tool_name == "update_architecture_status":
                return await self._update_architecture_status(**arguments)
            elif tool_name == "query_architecture_decisions":
                return self._query_architecture_decisions(**arguments)
            elif tool_name == "update_architecture":
                return self._update_architecture(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    def _delete_architecture(self, **params) -> list[TextContent]:
        """Delete a Proposed architecture decision that nothing depends on"""
        error = self._validate_required_params(params, ["architecture_id"])
        if error:
            return self._create_error_response(error)
        architecture_id = params["architecture_id"]
        try:
            removed = self._delete_entity(
                "architecture",
                "architecture",
                architecture_id,
                deletable_status="Proposed",
                blockers=ARCHITECTURE_DELETE_BLOCKERS,
            )
        except (LookupError, DeleteRefused) as e:
            return self._create_error_response(str(e))
        return self._create_above_fold_response(
            "SUCCESS", f"Architecture decision {architecture_id} deleted", f"🗑️ Removed {removed} link(s) it owned"
        )

    def _update_architecture(self, **params) -> list[TextContent]:
        """Edit a Proposed architecture decision; decided ones change through a superseding decision"""
        error = self._validate_required_params(params, ["architecture_id"])
        if error:
            return self._create_error_response(error)
        architecture_id = params["architecture_id"]
        changes = {column: params[name] for name, column in ARCHITECTURE_EDIT_COLUMNS.items() if name in params}
        amendment = (params.get("amendment") or "").strip()
        if amendment:
            return self._amend_architecture(architecture_id, amendment, changes, params)
        if not changes:
            return self._create_error_response(
                f"Nothing to update: pass at least one of {', '.join(ARCHITECTURE_EDIT_COLUMNS)}, or amendment"
            )

        def only_while_proposed(before: dict[str, Any]) -> None:
            if before["status"] != "Proposed":
                raise EditRefused(
                    f"Architecture decision {architecture_id} is {before['status']}; only Proposed decisions can be "
                    "edited. Correct it with amendment, which records a dated note beside the decision and leaves "
                    "its text as written, or record the change as a new decision with create_architecture_decision "
                    "and link it with create_relationship (relationship_type supersedes), which moves this one to "
                    "Superseded."
                )

        try:
            result = self._apply_edit(
                "architecture",
                "architecture",
                architecture_id,
                changes,
                editable=ARCHITECTURE_EDIT_COLUMNS.values(),
                json_fields=ARCHITECTURE_JSON_FIELDS,
                actor=params.get("actor") or "MCP User",
                reason=params.get("reason"),
                if_revision=params.get("if_revision"),
                check=only_while_proposed,
            )
        except (LookupError, RevisionConflict, EditRefused) as e:
            return self._create_error_response(str(e))
        return self._create_structured_response(
            "SUCCESS",
            f"Architecture decision {architecture_id} updated",
            {"id": architecture_id, "changed": result.changed, "revision": result.revision},
            self._describe_edit(result),
        )

    def _amend_architecture(
        self, architecture_id: str, amendment: str, changes: dict[str, Any], params: dict[str, Any]
    ) -> list[TextContent]:
        """Record a dated correction against an Accepted decision, leaving its own text as written (roadmap R20)"""
        if changes:
            return self._create_error_response(
                "Pass amendment on its own: it is recorded beside the decision rather than editing "
                f"{', '.join(sorted(changes))}. Amend the decision, or supersede it with a new one."
            )
        rows = self.db.get_records("architecture", "status", "id = ?", [architecture_id])
        if not rows:
            return self._create_error_response(f"Architecture decision {architecture_id} not found")

        status = rows[0]["status"]
        if status != "Accepted":
            return self._create_error_response(self._cannot_amend(architecture_id, status))

        # No UPDATE on architecture: the decision's columns and revision are left exactly as they were.
        self.db.insert_record(
            "lifecycle_events",
            {
                "entity_type": "architecture",
                "entity_id": architecture_id,
                "event_type": "amendment",
                "field": "decision_outcome",
                "to_value": amendment,
                "actor": params.get("actor") or "MCP User",
                "reason": params.get("reason"),
            },
        )

        recorded = amendments(self.db, architecture_id)
        structured = {"id": architecture_id, "status": status, "amendments": len(recorded)}
        return self._create_structured_response(
            "SUCCESS",
            f"Architecture decision {architecture_id} amended",
            structured,
            f"📝 {len(recorded)} amendment(s) | the decision's own text is unchanged",
        )

    @staticmethod
    def _cannot_amend(architecture_id: str, status: str) -> str:
        """Why this decision can't be amended, naming the operation that fits its status instead"""
        if status == "Proposed":
            return (
                f"Architecture decision {architecture_id} is Proposed; edit it instead, by passing the fields to "
                "change. An amendment corrects a decision that has already been accepted."
            )
        return (
            f"Architecture decision {architecture_id} is {status}; only an Accepted decision can be amended. "
            "A decision that was never accepted has nothing to correct."
        )

    async def _create_architecture_decision(self, **params) -> list[TextContent]:
        """Create ADR"""
        # Validate required parameters
        error = self._validate_required_params(params, ["requirement_ids", "title", "context", "decision"])
        if error:
            return self._create_error_response(error)

        try:
            # Get next ADR number
            adr_number = self.db.execute_query(
                """
                SELECT COALESCE(MAX(CAST(SUBSTR(id, 5, 4) AS INTEGER)), 0) + 1
                FROM architecture
                WHERE type = 'ADR'
            """,
                fetch_one=True,
            )[0]

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
                "authors": self._safe_json_dumps(params.get("authors", ["MCP User"])),
                **{
                    column: self._safe_json_dumps(params[column])
                    if column in ARCHITECTURE_JSON_FIELDS
                    else params[column]
                    for column in ARCHITECTURE_CURATED_PROPERTIES
                    if column in params
                },
            }

            # Insert ADR
            self.db.insert_record("architecture", arch_data)
            self._log_operation("architecture", adr_id, "created", ", ".join(params.get("authors") or ["MCP User"]))

            # Link to requirements
            for req_id in params["requirement_ids"]:
                self._link("requirement", req_id, "architecture", adr_id, "addresses")

            structured = {"id": adr_id, "status": "Proposed", "requirement_ids": params["requirement_ids"]}
            key_info = f"Architecture decision {adr_id} created"
            action_info = f"📐 {params['title']} | {params.get('status', 'Proposed')} | ADR"
            return self._create_structured_response("SUCCESS", key_info, structured, action_info)

        except Exception as e:
            return self._create_error_response("Failed to create architecture decision", e)

    async def _update_architecture_status(self, **params) -> list[TextContent]:
        """Move one architecture decision, or each of architecture_ids, to new_status (roadmap R9)"""
        error = self._validate_required_params(params, ["new_status"])
        if error:
            return self._create_error_response(error)
        return await self._change_statuses(
            params,
            "architecture_id",
            "Architecture",
            "architecture decisions",
            lambda architecture_id: self._change_architecture_status(architecture_id, params),
            "Failed to update architecture status",
        )

    async def _change_architecture_status(self, architecture_id: str, params: dict[str, Any]) -> StatusChange:
        """Move one architecture decision to new_status; Superseded follows its supersedes link (ADR-0003)"""
        current_arch = self.db.get_records("architecture", "status, superseded_by", "id = ?", [architecture_id])
        if not current_arch:
            raise StatusRefused("Architecture decision not found")

        current_status = current_arch[0]["status"]
        superseded_by = current_arch[0]["superseded_by"]
        new_status = params["new_status"]
        if new_status == "Superseded" and not superseded_by:
            raise StatusRefused(
                f"Record what supersedes {architecture_id} instead: create_relationship with the newer decision as "
                f"source_id, {architecture_id} as target_id and relationship_type supersedes moves it to Superseded"
            )
        if superseded_by and new_status != "Superseded":
            raise StatusRefused(
                f"{architecture_id} is superseded by {superseded_by}; delete that supersedes link before moving it "
                f"to {new_status}"
            )

        warnings = self._rule_warnings(self._move_reasons(current_status, new_status))

        # Update status. CURRENT_TIMESTAMP has to be SQL, not a bound value (F-42).
        self.db.execute_query(
            "UPDATE architecture SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [new_status, architecture_id],
        )

        # Add review comment if provided
        if params.get("comment"):
            self._add_review_comment("architecture", architecture_id, params["comment"])

        return StatusChange(architecture_id, current_status, new_status, warnings=warnings)

    @staticmethod
    def _move_reasons(current_status: str, new_status: str) -> list[str]:
        """Why this move is unusual: the decision's status vocabulary doesn't step that way (roadmap R8)"""
        allowed = ARCHITECTURE_TRANSITIONS.get(current_status)
        if allowed is None or new_status == current_status or new_status in allowed:
            return []
        return [
            f"Unusual move from {current_status} to {new_status}: a decision at {current_status} usually goes to "
            f"{', '.join(allowed) or 'nothing'}"
        ]

    def _query_architecture_decisions(self, **params) -> list[TextContent]:
        """Query architecture decisions with filters"""
        try:
            where_clauses = []
            where_params = []
            base_query = "SELECT * FROM architecture"

            # Handle requirement_id filter specially (requires join)
            if params.get("requirement_id"):
                base_query = """
                    SELECT a.* FROM architecture a
                    JOIN relationships rel ON rel.target_id = a.id
                    WHERE rel.source_type = 'requirement' AND rel.source_id = ?
                      AND rel.target_type = 'architecture' AND rel.relationship_type = 'addresses'
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

            # relationships also has created_at, so qualify it when joined
            base_query += " ORDER BY a.created_at DESC" if params.get("requirement_id") else " ORDER BY created_at DESC"

            decisions = self.db.execute_query(base_query, where_params, fetch_all=True, row_factory=True)

            # The full records, JSON fields parsed, as structured data next to the list (roadmap R10)
            structured = {
                "architecture_decisions": self._record_dicts(decisions, ARCHITECTURE_JSON_FIELDS),
                "count": len(decisions),
            }

            if not decisions:
                return self._create_structured_response(
                    "INFO", "No architecture decisions found", structured, "Try adjusting search criteria"
                )

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

            return self._create_structured_response("SUCCESS", key_info, structured, "", details)

        except Exception as e:
            return self._create_error_response("Failed to query architecture decisions", e)

    def _get_architecture_details(self, **params) -> list[TextContent]:
        """Get full architecture decision details"""
        # Validate required parameters
        error = self._validate_required_params(params, ["architecture_id"])
        if error:
            return self._create_error_response(error)

        try:
            # Get architecture decision
            arch_decisions = self.db.get_records("architecture", "*", "id = ?", [params["architecture_id"]])

            if not arch_decisions:
                return self._create_error_response("Architecture decision not found")

            arch = arch_decisions[0]
            deciders = ", ".join(self._safe_json_loads(arch["deciders"])) or "Not specified"
            superseded = f"\n- **Superseded By**: {arch['superseded_by']}" if arch["superseded_by"] else ""

            # Build detailed report
            report = f"""# Architecture Decision: {arch["id"]}

## Basic Information
- **Title**: {arch["title"]}
- **Type**: {arch["type"]}
- **Status**: {arch["status"]}
- **Created**: {arch["created_at"]}
- **Updated**: {arch["updated_at"]}
- **Revision**: {arch["revision"]}
- **Authors**: {arch["authors"] or "Not specified"}
- **Deciders**: {deciders}{superseded}

## Context
{arch["context"]}

## Decision
{arch["decision_outcome"]}
"""
            # With the decision, never merged into it: the reader sees what was decided and what was corrected.
            report += format_amendments(amendments(self.db, arch["id"]))

            if arch["decision_drivers"]:
                drivers = self._safe_json_loads(arch["decision_drivers"])
                if drivers:
                    report += "\n## Decision Drivers\n"
                    for driver in drivers:
                        report += f"- {driver}\n"

            if arch["considered_options"]:
                options = self._safe_json_loads(arch["considered_options"])
                if options:
                    report += "\n## Considered Options\n"
                    for option in options:
                        report += f"- {option}\n"

            if arch["consequences"]:
                consequences = self._safe_json_loads(arch["consequences"])
                if consequences:
                    report += "\n## Consequences\n"
                    if isinstance(consequences, dict):
                        for key, value in consequences.items():
                            report += f"**{key.title()}**: {value}\n"
                    else:
                        report += f"{consequences}\n"

            if arch["implementation_notes"]:
                report += f"\n## Implementation Notes\n{arch['implementation_notes']}\n"
            report += self._format_sections(arch, ARCHITECTURE_LIST_SECTIONS, "\n## {title}\n{body}")

            # Get linked requirements
            requirements = self.db.execute_query(
                """
                SELECT r.id, r.title FROM requirements r
                JOIN relationships rel ON rel.source_id = r.id
                WHERE rel.source_type = 'requirement' AND rel.target_type = 'architecture'
                  AND rel.target_id = ? AND rel.relationship_type = 'addresses'
            """,
                [params["architecture_id"]],
                fetch_all=True,
                row_factory=True,
            )

            if requirements:
                report += f"\n## Linked Requirements ({len(requirements)})\n"
                for req in requirements:
                    report += f"- {req['id']}: {req['title']}\n"

            # Design links (roadmap R9): tasks implementing this decision and the decisions it supersedes.
            report += self._format_linked(
                "Implemented By",
                "SELECT t.id, t.title, t.status FROM tasks t JOIN relationships rel ON rel.source_id = t.id "
                "WHERE rel.source_type = 'task' AND rel.target_type = 'architecture' AND rel.target_id = ? "
                "AND rel.relationship_type = 'implements' ORDER BY t.id",
                arch["id"],
            )
            report += self._format_linked(
                "Supersedes",
                "SELECT a.id, a.title, a.status FROM architecture a JOIN relationships rel ON rel.target_id = a.id "
                "WHERE rel.source_type = 'architecture' AND rel.source_id = ? AND rel.target_type = 'architecture' "
                "AND rel.relationship_type = 'supersedes' ORDER BY a.id",
                arch["id"],
            )

            report += self._format_comments("architecture", arch["id"])

            # Create above-the-fold response for architecture details
            key_info = f"Architecture {arch['id']} details"
            action_info = f"📐 {arch['title']} | {arch['status']} | {arch['type'] or 'ADR'}"
            return self._create_above_fold_response("INFO", key_info, action_info, report)

        except Exception as e:
            return self._create_error_response("Failed to get architecture details", e)
