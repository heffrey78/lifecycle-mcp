"""update_requirement, update_task and update_architecture (roadmap R6a: TASK-0019, TASK-0020, TASK-0021)."""

import re

from .test_delete_and_history import DECISION, approve, in_order
from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

REQ_1, REQ_2, REQ_3 = "REQ-0001-FUNC-00", "REQ-0002-FUNC-00", "REQ-0003-FUNC-00"
TASK = "TASK-0001-00-00"
REVIEW_FLAG = "Changed Since Last Review"


async def ok(server, name: str, arguments: dict) -> str:
    result = await call(server, name, arguments)
    assert not result.isError, text_of(result)
    return text_of(result)


async def requirement_details(server, requirement_id: str = REQ_1) -> str:
    return await ok(server, "get_requirement_details", {"requirement_id": requirement_id})


async def trace(server, requirement_id: str = REQ_1) -> str:
    return await ok(server, "trace_requirement", {"requirement_id": requirement_id})


async def task_details(server, task_id: str = TASK) -> str:
    return await ok(server, "get_task_details", {"task_id": task_id})


async def history(server, entity_id: str) -> str:
    return await ok(server, "get_entity_history", {"entity_id": entity_id})


async def create_task(server, title: str, requirement_ids=(REQ_1,), **extra) -> str:
    arguments = {"requirement_ids": list(requirement_ids), "priority": "P1", "title": title, **extra}
    return await ok(server, "create_task", arguments)


async def approved_requirement(server, title: str = "Searchable notes") -> None:
    created = await ok(server, "create_requirement", {**REQUIREMENT, "title": title})
    await approve(server, re.search(r"REQ-\d{4}-[A-Z]+-\d{2}", created).group())


# --- requirements ---------------------------------------------------------------------------------


async def test_draft_requirement_edit_shows_in_details_trace_and_export(mcp_server, tmp_path):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)

    updated = await ok(
        mcp_server,
        "update_requirement",
        {
            "requirement_id": REQ_1,
            "title": "Ranked search",
            "acceptance_criteria": ["Ranks by relevance"],
            "business_value": "Faster lookup",
        },
    )

    assert "Changed title, acceptance_criteria, business_value | revision 1" in updated
    assert "changed since last review" not in updated
    details = await requirement_details(mcp_server)
    assert "**Title**: Ranked search" in details and "- Ranks by relevance" in details
    assert "**Revision**: 1" in details and REVIEW_FLAG not in details
    assert "**Title**: Ranked search" in await trace(mcp_server)
    export = {
        "project_name": "notes",
        "output_directory": str(tmp_path),
        "include_tasks": False,
        "include_architecture": False,
    }
    await ok(mcp_server, "export_project_documentation", export)
    exported = (tmp_path / "notes-requirements.md").read_text(encoding="utf-8")
    assert "Ranked search" in exported and "- Ranks by relevance" in exported


async def test_approved_requirement_edit_without_reason_is_refused(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)

    for extra in ({}, {"reason": "   "}):
        refused = await call(mcp_server, "update_requirement", {"requirement_id": REQ_1, "title": "Other", **extra})
        assert refused.isError
        assert "is Approved; a reason is required" in text_of(refused)

    details = await requirement_details(mcp_server)
    assert "**Title**: Searchable notes" in details and "**Revision**: 0" in details
    assert "edited" not in await history(mcp_server, REQ_1)


async def test_approved_edit_is_flagged_as_changed_until_the_next_status_change(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)

    updated = await ok(
        mcp_server,
        "update_requirement",
        {
            "requirement_id": REQ_1,
            "acceptance_criteria": ["Returns matching notes", "Ranks by relevance"],
            "reason": "Owner asked for ranking",
            "actor": "agent",
        },
    )

    assert "changed since last review (Approved)" in updated
    flag = f"{REVIEW_FLAG}**: acceptance_criteria edited at Approved"
    assert flag in await requirement_details(mcp_server)
    traced = await trace(mcp_server)
    assert flag in traced and "⚠️ changed since last review" in traced
    status = await ok(mcp_server, "get_project_status", {})
    assert f"{REVIEW_FLAG} (1)" in status
    assert f"{REQ_1}: Searchable notes [Approved] edited acceptance_criteria" in status
    edits = await history(mcp_server, REQ_1)
    assert "edited acceptance_criteria by agent" in edits and "(reason: Owner asked for ranking)" in edits

    transition = {"requirement_id": REQ_1, "new_status": "Ready", "comment": "Ranking accepted"}
    await ok(mcp_server, "update_requirement_status", transition)

    assert REVIEW_FLAG not in await requirement_details(mcp_server)
    assert REVIEW_FLAG not in await ok(mcp_server, "get_project_status", {})


async def test_stale_if_revision_is_refused(mcp_server):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    await ok(mcp_server, "update_requirement", {"requirement_id": REQ_1, "title": "First", "if_revision": 0})

    refused = await call(
        mcp_server, "update_requirement", {"requirement_id": REQ_1, "title": "Second", "if_revision": 0}
    )

    assert refused.isError and "at revision 1, not 0" in text_of(refused)
    assert "**Title**: First" in await requirement_details(mcp_server)


async def test_update_without_fields_is_an_error(mcp_server):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)

    result = await call(mcp_server, "update_requirement", {"requirement_id": REQ_1, "reason": "nothing to say"})

    assert result.isError and "Nothing to update" in text_of(result)


# --- tasks -----------------------------------------------------------------------------------------


async def test_task_content_is_edited_in_one_call(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)
    await create_task(mcp_server, "Build index")

    edit = {
        "task_id": TASK,
        "title": "Build FTS index",
        "priority": "P0",
        "effort": "L",
        "user_story": "As a user I find notes fast",
        "acceptance_criteria": ["Index rebuilds on change"],
        "assignee": "agent",
    }
    assert "revision 1" in await ok(mcp_server, "update_task", edit)

    details = await task_details(mcp_server)
    for fragment in (
        "**Title**: Build FTS index",
        "**Priority**: P0",
        "**Effort**: L",
        "As a user I find notes fast",
        "- Index rebuilds on change",
        "**Assignee**: agent",
        "**Revision**: 1",
    ):
        assert fragment in details
    assert in_order(await history(mcp_server, TASK), "created", "edited title", "edited assignee")


async def test_subtask_moves_to_a_new_parent_and_keeps_its_id(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)
    await create_task(mcp_server, "Parent A")  # TASK-0001-00-00
    await create_task(mcp_server, "Child", parent_task_id="TASK-0001-00-00")  # TASK-0001-01-00
    await create_task(mcp_server, "Parent B")  # TASK-0002-00-00

    moved = await ok(mcp_server, "update_task", {"task_id": "TASK-0001-01-00", "parent_task_id": "TASK-0002-00-00"})

    assert "Changed parent_task_id" in moved
    assert "Subtasks" not in await task_details(mcp_server, "TASK-0001-00-00")
    assert "- TASK-0001-01-00: Child" in await task_details(mcp_server, "TASK-0002-00-00")
    assert "## Parent Task\n- TASK-0002-00-00: Parent B" in await task_details(mcp_server, "TASK-0001-01-00")
    assert "edited parent_task_id by MCP User: TASK-0001-00-00 → TASK-0002-00-00" in await history(
        mcp_server, "TASK-0001-01-00"
    )

    # The moved subtask still holds number 01 under task 0001, so a new subtask of A must not reuse it.
    assert "TASK-0001-02-00" in await create_task(mcp_server, "Second child", parent_task_id="TASK-0001-00-00")

    await ok(mcp_server, "update_task", {"task_id": "TASK-0001-01-00", "parent_task_id": ""})
    assert "Parent Task" not in await task_details(mcp_server, "TASK-0001-01-00")
    assert "Subtasks" not in await task_details(mcp_server, "TASK-0002-00-00")


async def test_self_parenting_and_cycles_are_refused(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)
    await create_task(mcp_server, "Parent A")  # TASK-0001-00-00
    await create_task(mcp_server, "Child", parent_task_id="TASK-0001-00-00")  # TASK-0001-01-00
    await create_task(mcp_server, "Grandchild", parent_task_id="TASK-0001-01-00")  # TASK-0001-02-00

    own = await call(mcp_server, "update_task", {"task_id": "TASK-0001-01-00", "parent_task_id": "TASK-0001-01-00"})
    assert own.isError and "cannot be its own parent" in text_of(own)
    cycle = await call(
        mcp_server, "update_task", {"task_id": TASK, "parent_task_id": "TASK-0001-02-00", "title": "Renamed"}
    )
    assert cycle.isError and "would create a cycle" in text_of(cycle)

    parent = await task_details(mcp_server)
    assert "Parent Task" not in parent and "**Title**: Parent A" in parent and "**Revision**: 0" in parent


async def test_requirement_links_are_replaced_behind_the_approval_gate(mcp_server):  # noqa: F811
    await approved_requirement(mcp_server)  # REQ_1
    await approved_requirement(mcp_server, "Tagging")  # REQ_2
    await ok(mcp_server, "create_requirement", {**REQUIREMENT, "title": "Draft idea"})  # REQ_3
    await create_task(mcp_server, "Build index")
    await ok(mcp_server, "update_task_status", {"task_id": TASK, "new_status": "Complete"})

    refused = await call(mcp_server, "update_task", {"task_id": TASK, "requirement_ids": [REQ_2, REQ_3]})
    assert refused.isError
    assert "Cannot link tasks to unapproved requirements" in text_of(refused)
    assert f"{REQ_3} (status: Draft)" in text_of(refused)
    assert "1/1 tasks complete" in await trace(mcp_server, REQ_1)

    moved = await ok(mcp_server, "update_task", {"task_id": TASK, "requirement_ids": [REQ_2]})

    assert "Changed requirement_ids" in moved
    assert "0/0 tasks complete" in await trace(mcp_server, REQ_1)
    assert "1/1 tasks complete" in await trace(mcp_server, REQ_2)
    assert "Linked Tasks" not in await requirement_details(mcp_server, REQ_1)
    assert f"- {REQ_2}: Tagging" in await task_details(mcp_server)


# --- architecture decisions ---------------------------------------------------------------------------


async def test_proposed_decision_is_edited_and_the_edit_logged(mcp_server):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    await ok(mcp_server, "create_architecture_decision", DECISION)

    edit = {
        "architecture_id": "ADR-0001",
        "decision": "SQLite FTS5 with trigram tokenizer",
        "decision_drivers": ["Fuzzy matching"],
        "reason": "Spike showed prefix search is not enough",
    }
    await ok(mcp_server, "update_architecture", edit)

    details = await ok(mcp_server, "get_architecture_details", {"architecture_id": "ADR-0001"})
    assert "SQLite FTS5 with trigram tokenizer" in details and "- Fuzzy matching" in details
    assert "**Revision**: 1" in details
    edits = await history(mcp_server, "ADR-0001")
    assert "edited decision_outcome by MCP User: SQLite FTS5 → SQLite FTS5 with trigram tokenizer" in edits
    assert "(reason: Spike showed prefix search is not enough)" in edits


async def test_decided_decision_edit_is_refused_with_supersede_guidance(mcp_server):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    await ok(mcp_server, "create_architecture_decision", DECISION)
    await ok(mcp_server, "update_architecture_status", {"architecture_id": "ADR-0001", "new_status": "Accepted"})

    refused = await call(mcp_server, "update_architecture", {"architecture_id": "ADR-0001", "title": "Use Tantivy"})

    assert refused.isError
    assert "is Accepted; only Proposed decisions can be edited" in text_of(refused)
    assert "Superseded" in text_of(refused)
    details = await ok(mcp_server, "get_architecture_details", {"architecture_id": "ADR-0001"})
    assert "**Title**: Use FTS5" in details
