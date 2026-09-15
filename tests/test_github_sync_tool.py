"""One GitHub sync tool, listed and routed only when LIFECYCLE_GITHUB=on (roadmap R16, TASK-0036).

No test here runs gh: the autouse guard in conftest.py fails any test that tries, and the sync methods are
replaced where a call would reach them.
"""

from lifecycle_mcp.github_utils import GITHUB_ENV_FLAG
from lifecycle_mcp.handlers.task_handler import TaskHandler

from .test_strict_tool_inputs import listed_tools
from .test_tool_results import call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

REMOVED = ("sync_task_from_github", "bulk_sync_github_tasks")


async def test_github_off_hides_the_sync_tool_and_refuses_calls_to_it(mcp_server):  # noqa: F811
    names = {tool.name for tool in await listed_tools(mcp_server)}

    assert "sync_github_tasks" not in names
    assert names.isdisjoint(REMOVED)
    for name in ("sync_github_tasks", *REMOVED):
        result = await call(mcp_server, name, {})
        assert result.isError and "Unknown tool" in text_of(result), name


async def test_github_on_lists_one_sync_tool_with_an_optional_task_id(mcp_server, monkeypatch):  # noqa: F811
    monkeypatch.setenv(GITHUB_ENV_FLAG, "on")

    tools = {tool.name: tool for tool in await listed_tools(mcp_server)}

    assert "sync_github_tasks" in tools and set(tools).isdisjoint(REMOVED)
    schema = tools["sync_github_tasks"].inputSchema
    assert set(schema["properties"]) == {"task_id"} and "required" not in schema


async def test_github_on_routes_one_task_or_all_linked_tasks(mcp_server, monkeypatch):  # noqa: F811
    monkeypatch.setenv(GITHUB_ENV_FLAG, "on")
    synced = []

    async def sync_one(self, task_id):
        synced.append(("one", task_id))
        return self._create_response(f"synced {task_id}")

    async def sync_all(self, **params):
        synced.append(("all", None))
        return self._create_response("synced all")

    monkeypatch.setattr(TaskHandler, "_sync_from_github", sync_one)
    monkeypatch.setattr(TaskHandler, "_bulk_sync_with_github", sync_all)

    one = await call(mcp_server, "sync_github_tasks", {"task_id": "TASK-0001-00-00"})
    everything = await call(mcp_server, "sync_github_tasks", {})

    assert not one.isError and not everything.isError
    assert synced == [("one", "TASK-0001-00-00"), ("all", None)]
