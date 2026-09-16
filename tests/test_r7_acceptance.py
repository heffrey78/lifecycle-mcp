"""R7 acceptance: each acceptance criterion of REQ-0003-FUNC-00 (what to work on next) through the MCP server layer,
one test per criterion in the requirement's order (TASK-0054).
"""

from .test_next_tasks import add_task, link, move, ready
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def test_1_the_ready_query_excludes_a_task_until_each_of_its_dependencies_is_complete(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    store = await add_task(mcp_server, ids["requirement"], "Store", "P1")
    search = await add_task(mcp_server, ids["requirement"], "Search", "P0")
    await link(mcp_server, search, ids["task"], "depends")
    await link(mcp_server, store, search, "blocks")

    assert search not in await ready(mcp_server)
    await move(mcp_server, ids["task"], "Complete")
    assert search not in await ready(mcp_server)
    await move(mcp_server, store, "Complete")
    assert (await ready(mcp_server))[0] == search


async def test_2_task_details_list_the_tasks_it_depends_on_and_the_tasks_it_blocks(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    middle = await add_task(mcp_server, ids["requirement"], "Middle", "P1")
    last = await add_task(mcp_server, ids["requirement"], "Last", "P2")
    await link(mcp_server, middle, ids["task"], "requires")
    await link(mcp_server, middle, last, "blocks")

    details = text_of(await call(mcp_server, "get_details", {"entity_id": middle}))

    assert f"## Depends On (1)\n- {ids['task']}: Build index [Not Started]" in details
    assert f"## Blocks (1)\n- {last}: Last [Not Started]" in details


async def test_3_a_blocked_task_with_a_reason_and_no_links_is_on_the_dashboard_by_name_with_its_reason(
    mcp_server,  # noqa: F811
):
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Blocked", comment="Waiting for the FTS5 build flag")

    result = await call(mcp_server, "get_project_status", {})

    assert f"- TASK {ids['task']}: Build index [Blocked]\n  Reason: Waiting for the FTS5 build flag" in text_of(result)
    assert result.structuredContent["blocked"] == [
        {
            "type": "task",
            "id": ids["task"],
            "title": "Build index",
            "status": "Blocked",
            "reason": "Waiting for the FTS5 build flag",
            "blocked_by": [],
        }
    ]
