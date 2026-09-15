"""Deleting early-stage records and get_entity_history (roadmap R6a: TASK-0022, TASK-0023)."""

from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

REQ_1, REQ_2 = "REQ-0001-FUNC-00", "REQ-0002-FUNC-00"


async def approve(server, requirement_id):
    for status in ("Under Review", "Approved"):
        result = await call(
            server, "update_requirement_status", {"requirement_id": requirement_id, "new_status": status}
        )
        assert not result.isError, text_of(result)


def in_order(text: str, *fragments: str) -> bool:
    positions = [text.find(fragment) for fragment in fragments]
    return -1 not in positions and positions == sorted(positions)


# --- requirements ---------------------------------------------------------------------------------


async def test_unlinked_draft_requirement_is_deleted_and_its_history_remains(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)

    deleted = await call(mcp_server, "delete_record", {"entity_id": REQ_1})

    assert not deleted.isError, text_of(deleted)
    assert (await call(mcp_server, "get_details", {"entity_id": REQ_1})).isError
    history = await call(mcp_server, "get_entity_history", {"entity_id": REQ_1})
    assert not history.isError
    assert in_order(text_of(history), "created by", "deleted by") and "record deleted" in text_of(history)


async def test_requirement_past_draft_is_refused(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)
    await call(mcp_server, "update_requirement_status", {"requirement_id": REQ_1, "new_status": "Under Review"})

    refused = await call(mcp_server, "delete_record", {"entity_id": REQ_1})

    assert refused.isError
    assert "is Under Review" in text_of(refused) and "Deprecated" in text_of(refused)


async def test_requirement_others_link_to_is_refused_until_they_are_gone(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)
    await call(mcp_server, "create_requirement", {**REQUIREMENT, "title": "Refinement"})
    link = {"source_id": REQ_2, "target_id": REQ_1, "relationship_type": "refines"}
    assert not (await call(mcp_server, "create_relationship", link)).isError

    refused = await call(mcp_server, "delete_record", {"entity_id": REQ_1})
    assert refused.isError and REQ_2 in text_of(refused)

    # REQ_2 owns its refines link, so it can go, and then nothing depends on REQ_1.
    assert not (await call(mcp_server, "delete_record", {"entity_id": REQ_2})).isError
    assert not (await call(mcp_server, "delete_record", {"entity_id": REQ_1})).isError


# --- tasks -----------------------------------------------------------------------------------------


async def test_tasks_with_subtasks_or_dependents_are_refused_and_leaves_are_deleted(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)
    await approve(mcp_server, REQ_1)
    base = {"requirement_ids": [REQ_1], "priority": "P1"}
    await call(mcp_server, "create_task", {**base, "title": "Parent"})  # TASK-0001-00-00
    await call(mcp_server, "create_task", {**base, "title": "Child", "parent_task_id": "TASK-0001-00-00"})
    await call(mcp_server, "create_task", {**base, "title": "Dependent"})  # TASK-0002-00-00
    dependency = {"source_id": "TASK-0002-00-00", "target_id": "TASK-0001-00-00", "relationship_type": "depends"}
    await call(mcp_server, "create_relationship", dependency)

    refused = await call(mcp_server, "delete_record", {"entity_id": "TASK-0001-00-00"})
    assert refused.isError
    assert "TASK-0001-01-00" in text_of(refused) and "TASK-0002-00-00" in text_of(refused)

    assert not (await call(mcp_server, "delete_record", {"entity_id": "TASK-0001-01-00"})).isError
    details = text_of(await call(mcp_server, "get_details", {"entity_id": REQ_1}))
    assert "Linked Tasks (2)" in details
    parent = text_of(await call(mcp_server, "get_details", {"entity_id": "TASK-0001-00-00"}))
    assert "Subtasks" not in parent

    assert not (await call(mcp_server, "delete_record", {"entity_id": "TASK-0002-00-00"})).isError
    assert not (await call(mcp_server, "delete_record", {"entity_id": "TASK-0001-00-00"})).isError
    details = text_of(await call(mcp_server, "get_details", {"entity_id": REQ_1}))
    assert "Linked Tasks" not in details


async def test_started_task_is_refused(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)
    await approve(mcp_server, REQ_1)
    await call(mcp_server, "create_task", {"requirement_ids": [REQ_1], "priority": "P1", "title": "Started"})
    await call(mcp_server, "update_task_status", {"task_id": "TASK-0001-00-00", "new_status": "In Progress"})

    refused = await call(mcp_server, "delete_record", {"entity_id": "TASK-0001-00-00"})

    assert refused.isError and "is In Progress" in text_of(refused)


# --- architecture decisions ---------------------------------------------------------------------------

DECISION = {"requirement_ids": [REQ_1], "title": "Use FTS5", "context": "Need search", "decision": "SQLite FTS5"}


async def test_proposed_decision_is_deleted_and_accepted_decision_is_refused(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)
    await call(mcp_server, "create_architecture_decision", DECISION)

    assert not (await call(mcp_server, "delete_record", {"entity_id": "ADR-0001"})).isError
    trace = text_of(await call(mcp_server, "trace_requirement", {"requirement_id": REQ_1}))
    assert "0 architecture" in trace

    await call(mcp_server, "create_architecture_decision", DECISION)
    await call(mcp_server, "update_architecture_status", {"architecture_id": "ADR-0001", "new_status": "Accepted"})
    refused = await call(mcp_server, "delete_record", {"entity_id": "ADR-0001"})
    assert refused.isError and "is Accepted" in text_of(refused)


# --- history -------------------------------------------------------------------------------------------


async def test_requirement_history_shows_status_changes_edits_and_comments(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)
    await call(
        mcp_server,
        "update_requirement_status",
        {"requirement_id": REQ_1, "new_status": "Under Review", "comment": "Ready for a look"},
    )
    mcp_server.requirement_handler._apply_edit(
        "requirements",
        "requirement",
        REQ_1,
        {"title": "Ranked search"},
        editable={"title"},
        actor="agent",
        reason="Title was too vague",
    )

    history = text_of(await call(mcp_server, "get_entity_history", {"entity_id": REQ_1}))

    assert in_order(history, "created", "status Draft → Under Review", "edited title by agent")
    assert "Searchable notes → Ranked search (reason: Title was too vague)" in history
    assert "comment by MCP User: Ready for a look" in history


async def test_task_and_decision_history(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)
    await approve(mcp_server, REQ_1)
    await call(mcp_server, "create_task", {"requirement_ids": [REQ_1], "priority": "P1", "title": "Build"})
    await call(mcp_server, "update_task_status", {"task_id": "TASK-0001-00-00", "new_status": "In Progress"})
    await call(mcp_server, "create_architecture_decision", DECISION)
    await call(mcp_server, "update_architecture_status", {"architecture_id": "ADR-0001", "new_status": "Accepted"})
    await call(mcp_server, "add_comment", {"entity_id": "ADR-0001", "comment": "Looks right"})

    task_history = text_of(await call(mcp_server, "get_entity_history", {"entity_id": "TASK-0001-00-00"}))
    assert in_order(task_history, "created", "status Not Started → In Progress")

    decision_history = text_of(await call(mcp_server, "get_entity_history", {"entity_id": "ADR-0001"}))
    assert in_order(decision_history, "created", "status Proposed → Accepted")
    assert "comment by MCP User: Looks right" in decision_history


async def test_history_for_unknown_or_invalid_ids_is_an_error(mcp_server):  # noqa: F811
    assert (await call(mcp_server, "get_entity_history", {"entity_id": "TASK-9999-00-00"})).isError
    assert (await call(mcp_server, "get_entity_history", {"entity_id": "NOT-AN-ID"})).isError
