"""R6a acceptance: each acceptance criterion of REQ-0009-FUNC-00 (edit records safely) through the MCP server layer.

One test per criterion, in the requirement's order (TASK-0024). Criterion 1 follows the owner's revision recorded on
TASK-0019: the changed-since-review flag is derived from lifecycle events and cleared by the next status change, not
by re-approval, and there is no separate acknowledgement tool.
"""

from .test_delete_and_history import DECISION, approve, in_order
from .test_strict_tool_inputs import UNEXPECTED, listed_tools
from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

REQ = "REQ-0001-FUNC-00"
TASK = "TASK-0001-00-00"
ADR = "ADR-0001"
FLAG = "Changed Since Last Review"


async def ok(server, name: str, arguments: dict) -> str:
    result = await call(server, name, arguments)
    assert not result.isError, text_of(result)
    return text_of(result)


async def approved_requirement(server) -> None:
    await ok(server, "create_requirement", REQUIREMENT)
    await approve(server, REQ)


async def test_1_criteria_edit_on_an_approved_requirement_is_visible_and_flagged_until_the_next_transition(
    mcp_server,  # noqa: F811
    tmp_path,
):
    await approved_requirement(mcp_server)

    edit = {
        "requirement_id": REQ,
        "acceptance_criteria": ["Returns matching notes", "Ranks results by relevance"],
        "reason": "Owner asked for ranking",
    }
    await ok(mcp_server, "update_requirement", edit)

    details = await ok(mcp_server, "get_requirement_details", {"requirement_id": REQ})
    assert "- Ranks results by relevance" in details
    assert f"{FLAG}**: acceptance_criteria edited at Approved" in details
    assert f"{FLAG}**: acceptance_criteria" in await ok(mcp_server, "trace_requirement", {"requirement_id": REQ})
    assert f"{FLAG} (1)" in await ok(mcp_server, "get_project_status", {})
    export = {"project_name": "r6a", "output_directory": str(tmp_path), "include_tasks": False}
    await ok(mcp_server, "export_project_documentation", export)
    assert "- Ranks results by relevance" in (tmp_path / "r6a-requirements.md").read_text(encoding="utf-8")

    transition = {"requirement_id": REQ, "new_status": "Ready", "comment": "Ranking accepted"}
    await ok(mcp_server, "update_requirement_status", transition)

    assert FLAG not in await ok(mcp_server, "get_requirement_details", {"requirement_id": REQ})
    assert FLAG not in await ok(mcp_server, "trace_requirement", {"requirement_id": REQ})
    assert FLAG not in await ok(mcp_server, "get_project_status", {})


async def test_2_the_same_edit_without_a_reason_is_refused(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)

    edit = {"requirement_id": REQ, "acceptance_criteria": ["Ranks results by relevance"]}
    refused = await call(mcp_server, "update_requirement", edit)

    assert refused.isError and "a reason is required" in text_of(refused)
    details = await ok(mcp_server, "get_requirement_details", {"requirement_id": REQ})
    assert "Ranks results by relevance" not in details and "**Revision**: 0" in details


async def test_3_editing_an_accepted_decision_is_refused_with_guidance_to_supersede_it(mcp_server):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    await ok(mcp_server, "create_architecture_decision", DECISION)
    await ok(mcp_server, "update_architecture_status", {"architecture_id": ADR, "new_status": "Accepted"})

    refused = await call(mcp_server, "update_architecture", {"architecture_id": ADR, "decision": "Use Tantivy"})

    assert refused.isError
    assert "only Proposed decisions can be edited" in text_of(refused)
    assert "create_architecture_decision" in text_of(refused) and "Superseded" in text_of(refused)
    assert "SQLite FTS5" in await ok(mcp_server, "get_architecture_details", {"architecture_id": ADR})


async def test_4_a_subtask_moved_to_a_new_parent_keeps_its_id_and_both_parents_list_it_correctly(
    mcp_server,  # noqa: F811
):
    await approved_requirement(mcp_server)
    base = {"requirement_ids": [REQ], "priority": "P1"}
    await ok(mcp_server, "create_task", {**base, "title": "Parent A"})  # TASK-0001-00-00
    await ok(mcp_server, "create_task", {**base, "title": "Child", "parent_task_id": TASK})  # TASK-0001-01-00
    await ok(mcp_server, "create_task", {**base, "title": "Parent B"})  # TASK-0002-00-00

    await ok(mcp_server, "update_task", {"task_id": "TASK-0001-01-00", "parent_task_id": "TASK-0002-00-00"})

    assert "Subtasks" not in await ok(mcp_server, "get_task_details", {"task_id": TASK})
    new_parent = await ok(mcp_server, "get_task_details", {"task_id": "TASK-0002-00-00"})
    assert "## Subtasks (1)\n- TASK-0001-01-00: Child" in new_parent
    child = await ok(mcp_server, "get_task_details", {"task_id": "TASK-0001-01-00"})
    assert "## Parent Task\n- TASK-0002-00-00: Parent B" in child
    assert "Found 3 task(s)" in await ok(mcp_server, "query_tasks", {})


# Schema-valid arguments for every create and update tool; each call adds one field no tool declares.
VALID_ARGUMENTS = {
    "create_requirement": REQUIREMENT,
    "create_task": {"requirement_ids": [REQ], "title": "Build index", "priority": "P1"},
    "create_architecture_decision": DECISION,
    "create_relationship": {"source_id": REQ, "target_id": TASK, "relationship_type": "implements"},
    "update_requirement": {"requirement_id": REQ, "title": "Ranked search"},
    "update_requirement_status": {"requirement_id": REQ, "new_status": "Under Review"},
    "update_task": {"task_id": TASK, "title": "Build FTS index"},
    "update_task_status": {"task_id": TASK, "new_status": "In Progress"},
    "update_architecture": {"architecture_id": ADR, "title": "Use FTS5 with trigrams"},
    "update_architecture_status": {"architecture_id": ADR, "new_status": "Accepted"},
}


async def test_5_an_unknown_field_on_any_create_or_update_tool_is_an_error_naming_the_field(mcp_server):  # noqa: F811
    # Guards the list above: a new create or update tool must be added to it. Diagram generation writes files,
    # not records, so it is not one of them.
    tools = {tool.name for tool in await listed_tools(mcp_server)} - {"create_architectural_diagrams"}
    assert {name for name in tools if name.startswith(("create_", "update_"))} == set(VALID_ARGUMENTS)

    for name, arguments in VALID_ARGUMENTS.items():
        result = await call(mcp_server, name, {**arguments, UNEXPECTED: "value"})
        assert result.isError, name
        assert UNEXPECTED in text_of(result), name

    assert "No requirements found" in await ok(mcp_server, "query_requirements", {})


async def test_6_an_unlinked_draft_requirement_is_deleted_and_one_with_tasks_is_refused_with_the_reason(
    mcp_server,  # noqa: F811
):
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    deleted = await ok(mcp_server, "delete_requirement", {"requirement_id": REQ})
    assert "deleted" in deleted
    assert (await call(mcp_server, "get_requirement_details", {"requirement_id": REQ})).isError

    await approved_requirement(mcp_server)  # recreated as REQ-0001-FUNC-00
    await ok(mcp_server, "create_task", {"requirement_ids": [REQ], "title": "Build index", "priority": "P1"})
    await ok(mcp_server, "create_requirement", {**REQUIREMENT, "title": "Tagging"})  # REQ-0002-FUNC-00, Draft
    link = {"source_id": "REQ-0002-FUNC-00", "target_id": TASK, "relationship_type": "implements"}
    await ok(mcp_server, "create_relationship", link)

    past_draft = await call(mcp_server, "delete_requirement", {"requirement_id": REQ})
    assert past_draft.isError and "is Approved" in text_of(past_draft)
    with_tasks = await call(mcp_server, "delete_requirement", {"requirement_id": "REQ-0002-FUNC-00"})
    assert with_tasks.isError and f"tasks: {TASK}" in text_of(with_tasks)


async def test_7_history_shows_every_edit_with_before_and_after_in_order_with_status_changes_and_comments(
    mcp_server,  # noqa: F811
):
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    review = {"requirement_id": REQ, "new_status": "Under Review", "comment": "Ready for a look"}
    await ok(mcp_server, "update_requirement_status", review)
    await ok(mcp_server, "update_requirement", {"requirement_id": REQ, "title": "Ranked search"})
    await ok(mcp_server, "update_requirement_status", {"requirement_id": REQ, "new_status": "Approved"})
    edit = {"requirement_id": REQ, "business_value": "Faster lookup", "reason": "Owner clarified value"}
    await ok(mcp_server, "update_requirement", edit)

    history = await ok(mcp_server, "get_entity_history", {"entity_id": REQ})

    assert in_order(
        history,
        "created",
        "status Draft → Under Review",
        "edited title by MCP User: Searchable notes → Ranked search",
        "status Under Review → Approved",
        "edited business_value by MCP User: (empty) → Faster lookup (reason: Owner clarified value)",
    )
    assert "comment by MCP User: Ready for a look" in history


async def test_8_an_update_with_a_stale_if_revision_fails_and_leaves_the_record_unchanged(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)
    await ok(mcp_server, "create_task", {"requirement_ids": [REQ], "title": "Build index", "priority": "P1"})
    await ok(mcp_server, "create_architecture_decision", DECISION)
    records = [
        ("update_requirement", "get_requirement_details", {"requirement_id": REQ, "reason": "Rename"}),
        ("update_task", "get_task_details", {"task_id": TASK}),
        ("update_architecture", "get_architecture_details", {"architecture_id": ADR}),
    ]

    for update, details, identity in records:
        await ok(mcp_server, update, {**identity, "title": "First", "if_revision": 0})

        stale = await call(mcp_server, update, {**identity, "title": "Second", "if_revision": 0})

        assert stale.isError and "at revision 1, not 0" in text_of(stale), update
        shown = await ok(mcp_server, details, {key: value for key, value in identity.items() if key != "reason"})
        assert "**Title**: First" in shown and "**Revision**: 1" in shown, update
