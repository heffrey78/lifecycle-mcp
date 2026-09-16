"""R8 acceptance: each acceptance criterion of REQ-0004-FUNC-00 (configurable workflow rules) through the MCP server
layer, one test per criterion in the requirement's order (TASK-0059).
"""

from lifecycle_mcp.rules import RULES_ENV_FLAG

from .test_next_tasks import move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)
from .test_workflow_rules import start, waiting_task


async def test_1_with_the_setting_unset_a_skipped_completion_still_happens_and_says_so(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    result = await start(mcp_server, ids["task"], "Complete")

    assert result.isError is False
    assert result.structuredContent["warnings"] == ["Completing a task that was never started"]
    assert "⚠️ Completing a task that was never started" in text_of(result)
    assert f"{ids['task']}" in text_of(await call(mcp_server, "query_tasks", {"status": "Complete"}))


async def test_2_warn_names_the_dependencies_that_are_not_finished(mcp_server):  # noqa: F811
    schema, api = await waiting_task(mcp_server)

    result = await start(mcp_server, api)

    assert result.isError is False
    assert result.structuredContent["warnings"] == [f"Dependencies not finished: {schema} (Not Started)"]


async def test_3_enforce_refuses_the_same_call_with_the_blocking_task_named(mcp_server, monkeypatch):  # noqa: F811
    schema, api = await waiting_task(mcp_server)
    monkeypatch.setenv(RULES_ENV_FLAG, "enforce")

    result = await start(mcp_server, api)

    assert result.isError is True and schema in text_of(result)
    assert f"Task {api} [Not Started]" in text_of(await call(mcp_server, "get_details", {"entity_id": api}))


async def test_4_an_abandoned_dependency_is_named_everywhere_and_can_be_cleared(mcp_server, monkeypatch):  # noqa: F811
    schema, api = await waiting_task(mcp_server)
    await move(mcp_server, schema, "Abandoned")

    # The dashboard lists what is waiting, so it names the abandoned dependency while the task is still Not Started.
    dashboard = await call(mcp_server, "get_project_status", {})
    assert f"  Abandoned dependencies: {schema}" in text_of(dashboard)

    warned = await start(mcp_server, api)
    assert warned.structuredContent["warnings"][0].startswith(f"Dependencies abandoned: {schema}")

    monkeypatch.setenv(RULES_ENV_FLAG, "enforce")
    refused = await start(mcp_server, api)
    assert refused.isError and schema in text_of(refused)

    dropped = await call(mcp_server, "delete_relationship", {"source_id": api, "target_id": schema})
    assert not dropped.isError
    assert (await start(mcp_server, api)).isError is False
    assert (await start(mcp_server, api, "Complete")).isError is False


async def test_5_off_warns_about_nothing_but_keeps_the_gates_that_always_applied(mcp_server, monkeypatch):  # noqa: F811
    ids = await populate(mcp_server)
    monkeypatch.setenv(RULES_ENV_FLAG, "off")

    skipped = await start(mcp_server, ids["task"], "Complete")
    assert skipped.isError is False and "warnings" not in skipped.structuredContent

    await call(mcp_server, "update_task_status", {"task_id": ids["task"], "new_status": "In Progress"})
    validated = await call(
        mcp_server, "update_requirement_status", {"requirement_id": ids["requirement"], "new_status": "Validated"}
    )
    assert validated.isError and "Cannot validate requirement with incomplete tasks" in text_of(validated)

    superseded = await call(
        mcp_server, "update_architecture_status", {"architecture_id": ids["adr"], "new_status": "Superseded"}
    )
    assert superseded.isError and "relationship_type supersedes" in text_of(superseded)


async def test_6_a_list_move_reports_its_warnings_per_task(mcp_server):  # noqa: F811
    schema, api = await waiting_task(mcp_server)
    await move(mcp_server, api, "In Progress")

    result = await call(mcp_server, "update_task_status", {"task_ids": [api, schema], "new_status": "Complete"})

    # api is moved first, while schema is still Not Started; schema is completed without ever being started.
    assert [entry.get("warnings", []) for entry in result.structuredContent["results"]] == [
        [f"Dependencies not finished: {schema} (Not Started)"],
        ["Completing a task that was never started"],
    ]
    assert f"  ⚠️ Dependencies not finished: {schema} (Not Started)" in text_of(result)
    assert "  ⚠️ Completing a task that was never started" in text_of(result)
