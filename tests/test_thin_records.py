"""New records say when they are thin for their kind (roadmap R11, TASK-0070)."""

from lifecycle_mcp.rules import RULES_ENV_FLAG

from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)

NFUNC = {
    "type": "NFUNC",
    "title": "Search stays fast",
    "priority": "P1",
    "current_state": "No measured target",
    "desired_state": "Search stays quick at 10k notes",
    "acceptance_criteria": ["Searching 10k notes feels instant"],
}


async def create_requirement(server, **overrides):
    return await call(server, "create_requirement", {**NFUNC, **overrides})


async def test_an_nfunc_requirement_without_validation_metrics_is_warned_about(mcp_server):  # noqa: F811
    result = await create_requirement(mcp_server)

    assert result.isError is False
    assert result.structuredContent["warnings"] == [
        "No validation_metrics: an NFUNC requirement needs one to be checkable later"
    ]
    assert "⚠️ No validation_metrics" in text_of(result)


async def test_filling_the_field_silences_it(mcp_server):  # noqa: F811
    result = await create_requirement(mcp_server, validation_metrics=["Search p95 under 50 ms at 10k notes"])

    assert result.isError is False and "warnings" not in result.structuredContent


async def test_any_requirement_without_acceptance_criteria_is_warned_about(mcp_server):  # noqa: F811
    bare = {key: value for key, value in REQUIREMENT.items() if key != "acceptance_criteria"}

    result = await call(mcp_server, "create_requirement", bare)

    assert result.isError is False
    assert result.structuredContent["warnings"] == [
        "No acceptance_criteria: every requirement needs one to be checkable later"
    ]


async def test_enforce_refuses_a_thin_requirement_and_writes_nothing(mcp_server, monkeypatch):  # noqa: F811
    monkeypatch.setenv(RULES_ENV_FLAG, "enforce")

    result = await create_requirement(mcp_server)

    assert result.isError is True and "validation_metrics" in text_of(result)
    listed = await call(mcp_server, "query_requirements", {})
    assert listed.structuredContent["count"] == 0


async def test_off_says_nothing(mcp_server, monkeypatch):  # noqa: F811
    monkeypatch.setenv(RULES_ENV_FLAG, "off")

    result = await create_requirement(mcp_server)

    assert result.isError is False and "warnings" not in result.structuredContent


async def test_a_high_priority_task_without_a_test_plan_is_warned_about(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    task = {"requirement_ids": [ids["requirement"]], "title": "Build ranking", "priority": "P0"}

    result = await call(mcp_server, "create_task", task)

    assert result.isError is False
    assert result.structuredContent["warnings"] == ["No test_plan: a P0 task needs one to show when it is done"]

    with_plan = await call(mcp_server, "create_task", {**task, "test_plan": ["Benchmark at 10k notes"]})
    assert "warnings" not in with_plan.structuredContent

    low = await call(mcp_server, "create_task", {**task, "priority": "P3"})
    assert "warnings" not in low.structuredContent
