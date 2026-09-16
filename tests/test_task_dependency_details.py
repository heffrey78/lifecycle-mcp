"""get_details on a task lists the tasks it waits on and the tasks waiting on it (roadmap R7, TASK-0051)."""

from .test_next_tasks import add_task, link, move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def details(server, task_id: str) -> str:
    result = await call(server, "get_details", {"entity_id": task_id})
    assert not result.isError, text_of(result)
    return text_of(result)


async def test_task_details_list_depends_on_and_blocks(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    schema = ids["task"]
    api = await add_task(mcp_server, ids["requirement"], "API", "P0")
    ui = await add_task(mcp_server, ids["requirement"], "UI", "P1")
    await link(mcp_server, api, schema, "depends")  # api waits on schema
    await link(mcp_server, api, ui, "blocks")  # ui waits on api
    await move(mcp_server, schema, "Complete")

    api_details = await details(mcp_server, api)
    assert f"## Depends On (1)\n- {schema}: Build index [Complete]" in api_details
    assert f"## Blocks (1)\n- {ui}: UI [Not Started]" in api_details

    ui_details = await details(mcp_server, ui)
    assert f"## Depends On (1)\n- {api}: API [Not Started]" in ui_details and "## Blocks" not in ui_details

    schema_details = await details(mcp_server, schema)
    assert f"## Blocks (1)\n- {api}: API [Not Started]" in schema_details and "## Depends On" not in schema_details
