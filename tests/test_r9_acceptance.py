"""R9 acceptance: each acceptance criterion of REQ-0005-FUNC-00 (design traceability and bulk transitions) through the
MCP server layer, one test per criterion in the requirement's order (TASK-0049).
"""

from .test_bulk_status import create_requirements
from .test_design_links import new_decision
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def ok(server, name: str, arguments: dict):
    result = await call(server, name, arguments)
    assert not result.isError, text_of(result)
    return result


async def test_1_details_list_implementing_tasks_the_superseding_decision_and_the_decisions_a_task_implements(
    mcp_server,  # noqa: F811
):
    ids = await populate(mcp_server)
    await ok(mcp_server, "update_architecture_status", {"architecture_id": ids["adr"], "new_status": "Accepted"})
    newer = await new_decision(mcp_server, ids["requirement"])
    implements = {"source_id": ids["task"], "target_id": ids["adr"], "relationship_type": "implements"}
    await ok(mcp_server, "create_relationship", implements)
    supersedes = {"source_id": newer, "target_id": ids["adr"], "relationship_type": "supersedes"}
    await ok(mcp_server, "create_relationship", supersedes)

    decision = text_of(await ok(mcp_server, "get_details", {"entity_id": ids["adr"]}))
    assert f"## Implemented By (1)\n- {ids['task']}: Build index [Not Started]" in decision
    assert f"- **Superseded By**: {newer}" in decision and "**Status**: Superseded" in decision

    task = text_of(await ok(mcp_server, "get_details", {"entity_id": ids["task"]}))
    assert f"## Implements Decisions (1)\n- {ids['adr']}: Use FTS5 [Superseded]" in task


async def test_2_approving_eight_draft_requirements_through_under_review_takes_one_call(mcp_server):  # noqa: F811
    ids = await create_requirements(mcp_server, 8)

    result = await ok(mcp_server, "update_requirement_status", {"requirement_ids": ids, "new_status": "Approved"})

    assert result.structuredContent["moved"] == 8
    for requirement_id in ids:
        history = text_of(await ok(mcp_server, "get_entity_history", {"entity_id": requirement_id}))
        assert history.index("status Draft → Under Review") < history.index("status Under Review → Approved")
    assert (await ok(mcp_server, "query_requirements", {"status": "Approved"})).structuredContent["count"] == 8


async def test_3_a_batch_with_one_refused_id_still_moves_the_others_and_names_the_refusal(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    second = {"requirement_ids": [ids["requirement"]], "title": "Rank results", "priority": "P2"}
    tasks = [ids["task"], "TASK-0099-00-00", (await ok(mcp_server, "create_task", second)).structuredContent["id"]]

    result = await ok(mcp_server, "update_task_status", {"task_ids": tasks, "new_status": "In Progress"})

    assert text_of(result).startswith("[WARNING] Moved 2 of 3 tasks to In Progress")
    assert "- TASK-0099-00-00: refused: Task not found" in text_of(result)
    assert [entry.get("error") for entry in result.structuredContent["results"]] == [None, "Task not found", None]
    for task_id in (tasks[0], tasks[2]):
        assert "[In Progress]" in text_of(await ok(mcp_server, "get_details", {"entity_id": task_id}))
