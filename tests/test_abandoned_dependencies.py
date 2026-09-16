"""An abandoned dependency is named as abandoned, not listed as an ordinary wait (roadmap R8, TASK-0058)."""

from .test_next_tasks import add_task, link, move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def waiting_on_first_task(server) -> tuple[str, str]:
    ids = await populate(server)
    api = await add_task(server, ids["requirement"], "API", "P0")
    await link(server, api, ids["task"], "depends")
    return ids["task"], api


def blocked_item(result, task_id: str) -> dict:
    return next(item for item in result.structuredContent["blocked"] if item["id"] == task_id)


async def test_the_dashboard_and_details_name_an_abandoned_dependency(mcp_server):  # noqa: F811
    schema, api = await waiting_on_first_task(mcp_server)
    await move(mcp_server, schema, "Abandoned")

    status = await call(mcp_server, "get_project_status", {})

    text = text_of(status)
    assert f"- TASK {api}: API [Not Started]" in text
    assert f"  Abandoned dependencies: {schema} (drop the link, or abandon this task too)" in text
    item = blocked_item(status, api)
    assert item["abandoned_dependencies"] == [schema] and item["blocked_by"] == []

    details = text_of(await call(mcp_server, "get_details", {"entity_id": api}))
    assert f"## Depends On (1)\n- {schema}: Build index [Abandoned]" in details
    assert f"⚠️ Abandoned dependencies: {schema}. Drop the link with delete_relationship" in details


async def test_an_unfinished_dependency_is_not_called_abandoned(mcp_server):  # noqa: F811
    schema, api = await waiting_on_first_task(mcp_server)

    status = await call(mcp_server, "get_project_status", {})

    item = blocked_item(status, api)
    assert item["blocked_by"] == [schema] and "abandoned_dependencies" not in item
    assert "Abandoned dependencies" not in text_of(status)
    assert "Abandoned dependencies" not in text_of(await call(mcp_server, "get_details", {"entity_id": api}))
