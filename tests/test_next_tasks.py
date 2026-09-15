"""What to work on next: tasks ready to start, dependencies in details and blocked reasons (roadmap R7)."""

from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def add_task(server, requirement_id: str, title: str, priority: str) -> str:
    arguments = {"requirement_ids": [requirement_id], "title": title, "priority": priority}
    result = await call(server, "create_task", arguments)
    assert not result.isError, text_of(result)
    return result.structuredContent["id"]


async def link(server, source_id: str, target_id: str, relationship_type: str) -> None:
    arguments = {"source_id": source_id, "target_id": target_id, "relationship_type": relationship_type}
    result = await call(server, "create_relationship", arguments)
    assert not result.isError, text_of(result)


async def move(server, task_id: str, new_status: str, **extra) -> None:
    result = await call(server, "update_task_status", {"task_id": task_id, "new_status": new_status, **extra})
    assert not result.isError, text_of(result)


async def ready(server, **filters) -> list[str]:
    result = await call(server, "query_tasks", {"ready": True, **filters})
    assert not result.isError, text_of(result)
    return [task["id"] for task in result.structuredContent["tasks"]]


# --- ready to start (TASK-0050) ------------------------------------------------------------------------------


async def test_ready_tasks_wait_for_every_dependency_and_come_by_priority(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    schema = ids["task"]  # P1
    api = await add_task(mcp_server, ids["requirement"], "API", "P0")
    ui = await add_task(mcp_server, ids["requirement"], "UI", "P1")
    docs = await add_task(mcp_server, ids["requirement"], "Docs", "P3")
    spike = await add_task(mcp_server, ids["requirement"], "Spike", "P0")
    await link(mcp_server, api, schema, "depends")  # api depends on schema
    await link(mcp_server, api, ui, "blocks")  # api blocks ui
    await link(mcp_server, docs, ui, "requires")  # docs requires ui
    await move(mcp_server, spike, "In Progress")

    assert await ready(mcp_server) == [schema]

    await move(mcp_server, schema, "Complete")
    assert await ready(mcp_server) == [api]

    await move(mcp_server, api, "Complete")
    assert await ready(mcp_server) == [ui]

    await move(mcp_server, ui, "In Progress")
    assert await ready(mcp_server) == []
    await move(mcp_server, ui, "Complete")
    assert await ready(mcp_server) == [docs]


async def test_ready_combines_with_other_filters_and_says_so(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await add_task(mcp_server, ids["requirement"], "Rank results", "P3")

    result = await call(
        mcp_server, "query_tasks", {"ready": True, "requirement_id": ids["requirement"], "priority": "P3"}
    )

    assert "ready to start" in text_of(result) and f"requirement: {ids['requirement']}" in text_of(result)
    assert [task["title"] for task in result.structuredContent["tasks"]] == ["Rank results"]
    other = await call(mcp_server, "query_tasks", {"ready": True, "requirement_id": "REQ-0099-FUNC-00"})
    assert other.structuredContent == {"tasks": [], "count": 0}
