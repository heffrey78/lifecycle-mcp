"""Tool results carry structuredContent next to their text, without an outputSchema (roadmap R10)."""

from .test_strict_tool_inputs import listed_tools
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def test_create_requirement_is_one_status_line_plus_structured_data(mcp_server):  # noqa: F811
    result = await call(mcp_server, "create_requirement", REQUIREMENT)

    assert result.isError is False
    assert text_of(result) == "[SUCCESS] Requirement REQ-0001-FUNC-00 created"
    assert result.structuredContent == {
        "id": "REQ-0001-FUNC-00",
        "type": "FUNC",
        "title": "Searchable notes",
        "priority": "P1",
        "status": "Draft",
    }


async def test_results_without_structured_data_leave_structured_content_empty(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)

    result = await call(mcp_server, "get_entity_history", {"entity_id": "REQ-0001-FUNC-00"})

    assert result.isError is False and result.structuredContent is None


async def test_no_tool_declares_an_output_schema(mcp_server):  # noqa: F811
    assert [tool.name for tool in await listed_tools(mcp_server) if tool.outputSchema is not None] == []


# --- query tools (TASK-0041: they replace the *_json tools) -------------------------------------------


async def test_query_tools_return_the_full_records_as_structured_data(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    edit = {"requirement_id": ids["requirement"], "business_value": "Faster lookup", "reason": "Value stated"}
    assert not (await call(mcp_server, "update_requirement", edit)).isError

    requirements = await call(mcp_server, "query_requirements", {})
    assert "Found 1 requirement(s)" in text_of(requirements)
    assert requirements.structuredContent["count"] == 1
    requirement = requirements.structuredContent["requirements"][0]
    assert requirement["id"] == ids["requirement"] and requirement["status"] == "Approved"
    assert requirement["acceptance_criteria"] == ["Returns matching notes"]
    assert requirement["business_value"] == "Faster lookup"  # plain text stays text

    tasks = await call(mcp_server, "query_tasks", {"requirement_id": ids["requirement"]})
    assert tasks.structuredContent["count"] == 1
    task = tasks.structuredContent["tasks"][0]
    assert task["id"] == ids["task"] and task["acceptance_criteria"] == []

    decisions = await call(mcp_server, "query_architecture_decisions", {"requirement_id": ids["requirement"]})
    assert decisions.structuredContent["count"] == 1
    decision = decisions.structuredContent["architecture_decisions"][0]
    assert decision["id"] == ids["adr"] and decision["decision_outcome"] == "SQLite FTS5"
    assert decision["authors"] == ["MCP User"]


async def test_an_empty_query_returns_an_empty_structured_list(mcp_server):  # noqa: F811
    result = await call(mcp_server, "query_tasks", {"status": "Blocked"})

    assert "No tasks found" in text_of(result)
    assert result.structuredContent == {"tasks": [], "count": 0}


async def test_the_json_twins_are_gone(mcp_server):  # noqa: F811
    for name in ("query_requirements_json", "query_tasks_json", "query_architecture_decisions_json"):
        result = await call(mcp_server, name, {})
        assert result.isError and "Unknown tool" in text_of(result), name
