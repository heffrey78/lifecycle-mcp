"""get_details, delete_record and add_comment work on any record's ID (roadmap R16, TASK-0034).

They replace get_requirement_details, get_task_details, get_architecture_details, delete_requirement, delete_task,
delete_architecture and add_architecture_review.
"""

from .test_delete_and_history import DECISION, approve, in_order
from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

REQ, TASK, ADR = "REQ-0001-FUNC-00", "TASK-0001-00-00", "ADR-0001"
REMOVED = (
    "get_requirement_details",
    "get_task_details",
    "get_architecture_details",
    "delete_requirement",
    "delete_task",
    "delete_architecture",
    "add_architecture_review",
)


async def ok(server, name: str, arguments: dict) -> str:
    result = await call(server, name, arguments)
    assert not result.isError, text_of(result)
    return text_of(result)


async def project(server) -> None:
    await ok(server, "create_requirement", REQUIREMENT)
    await approve(server, REQ)
    await ok(server, "create_task", {"requirement_ids": [REQ], "title": "Build index", "priority": "P1"})
    await ok(server, "create_architecture_decision", DECISION)


async def test_get_details_returns_the_report_for_each_record_type(mcp_server):  # noqa: F811
    await project(mcp_server)

    assert "# Requirement Details: REQ-0001-FUNC-00" in await ok(mcp_server, "get_details", {"entity_id": REQ})
    assert "# Task Details: TASK-0001-00-00" in await ok(mcp_server, "get_details", {"entity_id": TASK})
    assert "# Architecture Decision: ADR-0001" in await ok(mcp_server, "get_details", {"entity_id": ADR})


async def test_malformed_and_unknown_ids_are_refused(mcp_server):  # noqa: F811
    for tool, extra in (("get_details", {}), ("delete_record", {}), ("add_comment", {"comment": "x"})):
        malformed = await call(mcp_server, tool, {"entity_id": "NOTE-1", **extra})
        assert malformed.isError and "Expected an ID like REQ-0001-FUNC-00, TASK-0001-00-00 or ADR-0001" in text_of(
            malformed
        ), tool

    missing = await call(mcp_server, "get_details", {"entity_id": "TASK-0099-00-00"})
    assert missing.isError and "not found" in text_of(missing)
    no_record = await call(mcp_server, "add_comment", {"entity_id": "REQ-0099-FUNC-00", "comment": "x"})
    assert no_record.isError and "No requirement REQ-0099-FUNC-00 found" in text_of(no_record)


async def test_delete_record_keeps_each_types_rules(mcp_server):  # noqa: F811
    await project(mcp_server)

    requirement = await call(mcp_server, "delete_record", {"entity_id": REQ})
    assert requirement.isError and "is Approved" in text_of(requirement)

    await ok(
        mcp_server,
        "create_task",
        {"requirement_ids": [REQ], "title": "Child", "priority": "P1", "parent_task_id": TASK},
    )
    parent = await call(mcp_server, "delete_record", {"entity_id": TASK})
    assert parent.isError and "subtasks: TASK-0001-01-00" in text_of(parent)

    assert "deleted" in await ok(mcp_server, "delete_record", {"entity_id": "TASK-0001-01-00"})
    assert "deleted" in await ok(mcp_server, "delete_record", {"entity_id": ADR})
    assert (await call(mcp_server, "get_details", {"entity_id": ADR})).isError


async def test_comments_on_every_record_type_show_in_details_and_history(mcp_server):  # noqa: F811
    await project(mcp_server)

    for entity_id, author in ((REQ, "Owner"), (TASK, None), (ADR, "Reviewer")):
        arguments = {"entity_id": entity_id, "comment": f"Looked at {entity_id}"}
        if author:
            arguments["author"] = author
        assert f"Comment added to {entity_id}" in await ok(mcp_server, "add_comment", arguments)

    requirement = await ok(mcp_server, "get_details", {"entity_id": REQ})
    assert "## Comments (" in requirement and "- **Owner** (" in requirement
    assert f"): Looked at {REQ}" in requirement
    task = await ok(mcp_server, "get_details", {"entity_id": TASK})
    assert "## Comments (1)" in task and "**MCP User** (" in task and f"Looked at {TASK}" in task
    decision = await ok(mcp_server, "get_details", {"entity_id": ADR})
    assert "## Comments (1)" in decision and "**Reviewer** (" in decision

    history = await ok(mcp_server, "get_entity_history", {"entity_id": TASK})
    assert in_order(history, "created", f"comment by MCP User: Looked at {TASK}")


async def test_the_replaced_tools_are_gone(mcp_server):  # noqa: F811
    for name in REMOVED:
        result = await call(mcp_server, name, {})
        assert result.isError and "Unknown tool" in text_of(result), name
