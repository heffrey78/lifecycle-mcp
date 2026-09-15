"""Status tools move a list of IDs in one call, with a result per ID (roadmap R9, ADR-0003)."""

from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def create_requirements(server, count: int) -> list[str]:
    ids = []
    for number in range(1, count + 1):
        result = await call(server, "create_requirement", {**REQUIREMENT, "title": f"Requirement {number}"})
        assert not result.isError, text_of(result)
        ids.append(result.structuredContent["id"])
    return ids


# --- list calls (TASK-0045) -------------------------------------------------------------------------------


async def test_a_list_moves_every_id_and_reports_each(mcp_server):  # noqa: F811
    ids = await create_requirements(mcp_server, 3)

    result = await call(
        mcp_server,
        "update_requirement_status",
        {"requirement_ids": ids, "new_status": "Under Review", "comment": "Batch review"},
    )

    assert result.isError is False
    assert text_of(result).startswith("[SUCCESS] Moved 3 of 3 requirements to Under Review")
    assert result.structuredContent == {
        "results": [
            {"id": requirement_id, "from_status": "Draft", "to_status": "Under Review"} for requirement_id in ids
        ],
        "moved": 3,
        "refused": 0,
    }
    for requirement_id in ids:
        assert f"- {requirement_id}: Draft → Under Review" in text_of(result)
        assert "Batch review" in text_of(await call(mcp_server, "get_details", {"entity_id": requirement_id}))


async def test_refused_ids_are_named_and_the_rest_still_move(mcp_server):  # noqa: F811
    ids = await create_requirements(mcp_server, 2)
    await call(mcp_server, "update_requirement_status", {"requirement_id": ids[1], "new_status": "Under Review"})
    missing = "REQ-0099-FUNC-00"

    result = await call(
        mcp_server,
        "update_requirement_status",
        {"requirement_ids": [ids[0], missing, ids[1], ids[0]], "new_status": "Under Review"},
    )

    assert result.isError is False
    text = text_of(result)
    assert text.startswith("[WARNING] Moved 1 of 3 requirements to Under Review")
    assert f"- {ids[0]}: Draft → Under Review" in text
    assert f"- {missing}: refused: Requirement not found" in text
    assert f"- {ids[1]}: refused: Invalid transition from Under Review to Under Review" in text
    assert result.structuredContent["moved"] == 1 and result.structuredContent["refused"] == 2
    assert result.structuredContent["results"][1] == {"id": missing, "error": "Requirement not found"}


async def test_a_list_where_nothing_moves_is_an_error(mcp_server):  # noqa: F811
    result = await call(
        mcp_server, "update_task_status", {"task_ids": ["TASK-0098-00-00", "TASK-0099-00-00"], "new_status": "Blocked"}
    )

    assert result.isError is True
    text = text_of(result)
    assert "Moved 0 of 2 tasks to Blocked" in text
    assert "- TASK-0098-00-00: refused: Task not found" in text and "- TASK-0099-00-00: refused: Task not found" in text


async def test_the_single_and_list_forms_are_exclusive(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    both = await call(
        mcp_server, "update_task_status", {"task_id": ids["task"], "task_ids": [ids["task"]], "new_status": "Blocked"}
    )
    assert both.isError and "Pass task_id or task_ids, not both" in text_of(both)

    neither = await call(mcp_server, "update_architecture_status", {"new_status": "Accepted"})
    assert neither.isError and "Missing required parameters: architecture_id or architecture_ids" in text_of(neither)

    empty = await call(mcp_server, "update_requirement_status", {"requirement_ids": [], "new_status": "Draft"})
    assert empty.isError and "requirement_id or requirement_ids" in text_of(empty)


async def test_task_and_architecture_lists_and_the_unchanged_single_id_result(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    second = await call(
        mcp_server, "create_task", {"requirement_ids": [ids["requirement"]], "title": "Rank results", "priority": "P2"}
    )
    tasks = [ids["task"], second.structuredContent["id"]]

    moved = await call(
        mcp_server, "update_task_status", {"task_ids": tasks, "new_status": "In Progress", "assignee": "sam"}
    )
    assert moved.structuredContent["moved"] == 2
    for task_id in tasks:
        details = text_of(await call(mcp_server, "get_details", {"entity_id": task_id}))
        assert "[In Progress]" in details and "**Assignee**: sam" in details

    decisions = await call(
        mcp_server, "update_architecture_status", {"architecture_ids": [ids["adr"]], "new_status": "Accepted"}
    )
    assert decisions.structuredContent == {
        "results": [{"id": ids["adr"], "from_status": "Proposed", "to_status": "Accepted"}],
        "moved": 1,
        "refused": 0,
    }

    single = await call(
        mcp_server, "update_architecture_status", {"architecture_id": ids["adr"], "new_status": "Deprecated"}
    )
    assert text_of(single) == "[SUCCESS] Architecture ADR-0001 updated\n📈 Accepted → Deprecated"
    assert single.structuredContent == {"id": ids["adr"], "from_status": "Accepted", "to_status": "Deprecated"}
