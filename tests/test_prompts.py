"""The server offers a requirement capture prompt (roadmap R11, TASK-0071)."""

import pytest
from mcp import types

from lifecycle_mcp.prompts import CAPTURE_REQUIREMENT, RECONCILE_REQUIREMENTS, render_prompt

from .test_tool_results import call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)


async def list_prompts(server) -> list[types.Prompt]:
    handler = server.server.request_handlers[types.ListPromptsRequest]
    request = types.ListPromptsRequest(method="prompts/list")
    return (await handler(request)).root.prompts


async def get_prompt(server, name: str, arguments: dict | None = None) -> types.GetPromptResult:
    handler = server.server.request_handlers[types.GetPromptRequest]
    request = types.GetPromptRequest(
        method="prompts/get", params=types.GetPromptRequestParams(name=name, arguments=arguments)
    )
    return (await handler(request)).root


async def test_the_server_offers_the_capture_prompt(mcp_server):  # noqa: F811
    prompts = await list_prompts(mcp_server)

    assert [prompt.name for prompt in prompts] == [CAPTURE_REQUIREMENT, RECONCILE_REQUIREMENTS]
    assert prompts[0].description
    assert [argument.name for argument in prompts[0].arguments] == ["about"]


async def test_the_prompt_explains_the_fields_and_shows_an_example(mcp_server):  # noqa: F811
    result = await get_prompt(mcp_server, CAPTURE_REQUIREMENT)

    text = result.messages[0].content.text
    for field in ("type", "title", "priority", "current_state", "desired_state", "acceptance_criteria"):
        assert field in text, field
    assert "validation_metrics" in text and "p95" in text
    assert "create_requirement(" in text


async def test_what_the_person_said_is_carried_into_the_prompt(mcp_server):  # noqa: F811
    result = await get_prompt(mcp_server, CAPTURE_REQUIREMENT, {"about": "exports keep timing out"})

    assert "exports keep timing out" in result.messages[0].content.text


async def test_an_unknown_prompt_names_what_is_offered(mcp_server):  # noqa: F811
    with pytest.raises(ValueError, match=CAPTURE_REQUIREMENT):
        render_prompt("interview_requirement")


async def test_following_the_prompt_produces_a_requirement_with_the_curated_fields(mcp_server):  # noqa: F811
    # What the prompt's worked example tells the client's model to send.
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "NFUNC",
            "title": "Search stays fast as notes grow",
            "priority": "P1",
            "current_state": "Search runs unindexed; at 10k notes a query takes about 900 ms.",
            "desired_state": "Search stays quick as the collection grows.",
            "acceptance_criteria": ["A search over 10k notes returns in under 50 ms at p95"],
            "validation_metrics": ["Search p95 under 50 ms at 10k notes"],
        },
    )

    assert not result.isError, text_of(result)
    assert "warnings" not in result.structuredContent  # nothing thin about it
    details = text_of(await call(mcp_server, "get_details", {"entity_id": result.structuredContent["id"]}))
    assert "Search p95 under 50 ms at 10k notes" in details
