"""R19 acceptance: each acceptance criterion of REQ-0003-INTF-00 (errors that name the parameter that would have
worked) through the MCP server layer, one test per criterion in the requirement's order.

The failure this closes (F-54): a list passed to the singular `requirement_id` was refused with a message naming
the value and never the parameter one character away that would have taken it.
"""

import jsonschema

from lifecycle_mcp.server import ToolCallError

from .test_strict_tool_inputs import listed_tools
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def schema_of(server, tool_name: str) -> dict:
    return next(tool.inputSchema for tool in await listed_tools(server) if tool.name == tool_name)


def minimal(schema: dict, **overrides) -> dict:
    """A payload satisfying the schema's required fields, so one deliberate mistake is the only error."""
    payload = {}
    for name in schema.get("required", []):
        subschema = schema["properties"][name]
        payload[name] = subschema["enum"][0] if "enum" in subschema else "x"
    payload.update(overrides)
    return payload


async def test_1_a_list_passed_to_requirement_id_names_requirement_ids(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    result = await call(
        mcp_server, "update_requirement_status", {"requirement_id": [ids["requirement"]], "new_status": "Architecture"}
    )

    assert result.isError is True
    message = text_of(result)
    assert "requirement_ids" in message
    # The refused parameter and the type it expects are still named.
    assert "requirement_id takes a string" in message
    assert "requirement_ids takes an array and accepts what you passed" in message


async def test_2_the_same_holds_for_task_id_and_architecture_id(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    for tool, parameter, value, status in (
        ("update_task_status", "task_id", ids["task"], "In Progress"),
        ("update_architecture_status", "architecture_id", ids["adr"], "Accepted"),
    ):
        result = await call(mcp_server, tool, {parameter: [value], "new_status": status})

        assert result.isError is True, tool
        assert f"{parameter}s takes an array and accepts what you passed" in text_of(result), tool


async def test_3_a_type_error_with_no_such_sibling_is_unchanged(mcp_server):  # noqa: F811
    arguments = {**REQUIREMENT, "title": ["Searchable notes"]}

    result = await call(mcp_server, "create_requirement", arguments)

    assert result.isError is True
    # Identical to the message the MCP layer produced before the server took validation over: no parameter of
    # create_requirement is both close to "title" in name and willing to take a list.
    try:
        jsonschema.validate(instance=arguments, schema=await schema_of(mcp_server, "create_requirement"))
    except jsonschema.ValidationError as e:
        assert text_of(result) == f"Input validation error: {e.message}"
    else:
        raise AssertionError("expected the arguments to be refused")


async def test_4_an_unknown_field_is_still_refused_by_name(mcp_server):  # noqa: F811
    result = await call(mcp_server, "create_requirement", {**REQUIREMENT, "not_a_real_field": ["Mobile apps"]})

    assert result.isError is True
    assert "not_a_real_field" in text_of(result)


async def test_5_every_singular_and_plural_pair_in_the_surface_suggests_the_other(mcp_server):  # noqa: F811
    """The requirement's validation metric, over the live surface rather than a list of known pairs."""
    pairs = [
        (tool.name, name, f"{name}s")
        for tool in await listed_tools(mcp_server)
        for name in tool.inputSchema.get("properties", {})
        if f"{name}s" in tool.inputSchema.get("properties", {})
    ]
    assert pairs, "expected the surface to declare singular/plural parameter pairs"

    unsuggested = []
    for tool_name, singular, plural in pairs:
        schema = await schema_of(mcp_server, tool_name)
        try:
            mcp_server._validate_arguments(tool_name, minimal(schema, **{singular: ["REQ-0001-FUNC-00"]}))
        except ToolCallError as e:
            if plural not in str(e):
                unsuggested.append(f"{tool_name}.{singular}: {e}")
        else:
            unsuggested.append(f"{tool_name}.{singular}: a list was not refused")
    assert unsuggested == []
