"""Tool results carry structuredContent next to their text, without an outputSchema (roadmap R10)."""

from .test_strict_tool_inputs import listed_tools
from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)


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
