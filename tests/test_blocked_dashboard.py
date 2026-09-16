"""The dashboard lists every blocked task with its reason and what it waits on (roadmap R7, TASK-0053)."""

from .test_next_tasks import add_task, link, move
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def project_status(server, **arguments):
    result = await call(server, "get_project_status", arguments)
    assert not result.isError, text_of(result)
    return result


async def test_blocked_and_waiting_tasks_are_listed_with_reasons_and_dependencies(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    schema = ids["task"]
    api = await add_task(mcp_server, ids["requirement"], "API", "P0")
    benchmark = await add_task(mcp_server, ids["requirement"], "Benchmark", "P1")
    docs = await add_task(mcp_server, ids["requirement"], "Docs", "P3")
    await link(mcp_server, api, schema, "depends")  # Not Started and waiting on schema
    await move(mcp_server, benchmark, "Blocked", comment="Needs a 10k-note fixture")  # Blocked, no links
    await move(mcp_server, docs, "Blocked")  # Blocked, no reason

    result = await project_status(mcp_server)

    text = text_of(result)
    assert "## ⚠️ Blocked Items (3)" in text and "⚠️ 3 blocked" in text
    assert f"- TASK {api}: API [Not Started]\n  Waiting on: {schema}\n" in text
    assert f"- TASK {benchmark}: Benchmark [Blocked]\n  Reason: Needs a 10k-note fixture\n" in text
    assert f"- TASK {docs}: Docs [Blocked]\n  Reason: Not given\n" in text
    assert result.structuredContent["blocked"] == [
        {"type": "task", "id": api, "title": "API", "status": "Not Started", "reason": None, "blocked_by": [schema]},
        {
            "type": "task",
            "id": benchmark,
            "title": "Benchmark",
            "status": "Blocked",
            "reason": "Needs a 10k-note fixture",
            "blocked_by": [],
        },
        {"type": "task", "id": docs, "title": "Docs", "status": "Blocked", "reason": None, "blocked_by": []},
    ]


async def test_waiting_ends_with_the_dependency_nothing_is_cut_off_and_requirements_still_show(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    api = await add_task(mcp_server, ids["requirement"], "API", "P0")
    await link(mcp_server, api, ids["task"], "depends")
    stalled = [await add_task(mcp_server, ids["requirement"], f"Stalled {number}", "P2") for number in range(12)]
    moved = await call(
        mcp_server, "update_task_status", {"task_ids": stalled, "new_status": "Blocked", "comment": "Vendor outage"}
    )
    assert moved.structuredContent["moved"] == 12
    saved_searches = await call(mcp_server, "create_requirement", {**REQUIREMENT, "title": "Saved searches"})
    later = saved_searches.structuredContent["id"]
    await link(mcp_server, later, ids["requirement"], "depends")

    await move(mcp_server, ids["task"], "Complete")
    result = await project_status(mcp_server)

    blocked = result.structuredContent["blocked"]
    assert [item["id"] for item in blocked if item["type"] == "task"] == stalled  # api no longer waits
    assert blocked[-1] == {
        "type": "requirement",
        "id": later,
        "title": "Saved searches",
        "status": "Draft",
        "reason": None,
        "blocked_by": [ids["requirement"]],
    }
    assert "## ⚠️ Blocked Items (13)" in text_of(result) and f"- TASK {stalled[-1]}: Stalled 11 [Blocked]" in text_of(
        result
    )

    hidden = await project_status(mcp_server, include_blocked=False)
    assert "Blocked Items" not in text_of(hidden) and "blocked" not in hidden.structuredContent
