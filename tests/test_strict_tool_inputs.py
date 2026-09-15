"""Every tool rejects fields it does not declare, instead of silently dropping them (roadmap R6a)."""

import jsonschema
from mcp import types

from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

UNEXPECTED = "not_a_real_field"


async def listed_tools(server) -> list[types.Tool]:
    handler = server.server.request_handlers[types.ListToolsRequest]
    return (await handler(types.ListToolsRequest(method="tools/list"))).root.tools


async def test_every_tool_schema_forbids_undeclared_fields(mcp_server):  # noqa: F811
    tools = await listed_tools(mcp_server)
    assert len(tools) >= 20  # a floor that catches an empty or broken listing; the exact count is budgeted
    assert [tool.name for tool in tools if tool.inputSchema.get("additionalProperties") is not False] == []


async def test_every_tool_names_the_unexpected_field(mcp_server):  # noqa: F811
    unnamed = []
    for tool in await listed_tools(mcp_server):
        errors = jsonschema.Draft7Validator(tool.inputSchema).iter_errors({UNEXPECTED: 1})
        if not any(UNEXPECTED in error.message for error in errors):
            unnamed.append(tool.name)
    assert unnamed == []


async def test_unknown_field_is_refused_through_the_mcp_layer_and_nothing_is_written(mcp_server):  # noqa: F811
    result = await call(mcp_server, "create_requirement", {**REQUIREMENT, UNEXPECTED: ["Mobile apps"]})
    assert result.isError is True
    assert UNEXPECTED in text_of(result)

    listing = await call(mcp_server, "query_requirements", {})
    assert "No requirements found" in text_of(listing)


async def test_declared_fields_still_work(mcp_server):  # noqa: F811
    result = await call(mcp_server, "create_requirement", REQUIREMENT)
    assert result.isError is False, text_of(result)
