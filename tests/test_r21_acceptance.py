"""R21 acceptance: each acceptance criterion of REQ-0012-FUNC-00 (reconcile requirements from an existing source).

Requirements entered this tracker one at a time, typed by someone who already knew theirs was new, so a body of work
that predates the tracker had no way in that did not duplicate what was stored. The comparison is a prompt rather than
a tool: the client's model reads the source, the server keeps no session, and server-side intelligence is what sank
the interview tools (F-07, F-08). What the server does add is the one thing a prompt cannot - somewhere to record that
a requirement was derived rather than stated, and the Draft status that keeps a derived one from counting as approved.
"""

import os

from lifecycle_mcp.prompts import CAPTURE_REQUIREMENT, RECONCILE_REQUIREMENTS

from .test_prompts import get_prompt, list_prompts
from .test_tool_results import call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

DERIVED = {
    "type": "FUNC",
    "title": "The server refuses undeclared parameters",
    "priority": "P2",
    "current_state": "Read from server.py: every tool schema carries additionalProperties false.",
    "desired_state": "Undeclared fields are refused by name.",
    "origin": "derived-from-code",
}
STATED = {
    "type": "FUNC",
    "title": "Someone asked for this one",
    "priority": "P2",
    "current_state": "A person said so.",
    "desired_state": "It happens.",
}


async def create(server, payload: dict) -> str:
    result = await call(server, "create_requirement", payload)
    assert not result.isError, text_of(result)
    return result.structuredContent["id"]


async def details(server, entity_id: str) -> str:
    result = await call(server, "get_details", {"entity_id": entity_id})
    assert not result.isError, text_of(result)
    return text_of(result)


async def exported_requirements(server, tmp_path) -> str:
    result = await call(
        server, "export_project_documentation", {"project_name": "R21", "output_directory": str(tmp_path)}
    )
    assert not result.isError, text_of(result)
    name = next(f for f in os.listdir(tmp_path) if "requirement" in f.lower())
    with open(os.path.join(tmp_path, name), encoding="utf-8") as handle:
        return handle.read()


async def test_1_the_prompt_says_to_read_the_stored_set_before_classifying_anything(mcp_server):  # noqa: F811
    result = await get_prompt(mcp_server, RECONCILE_REQUIREMENTS)

    text = result.messages[0].content.text
    assert "query_requirements" in text
    assert text.index("query_requirements") < text.index("create_requirement"), "compare before creating"
    for bucket in ("NEW", "AMENDS", "ALREADY COVERED", "CONTRADICTS"):
        assert bucket in text, bucket


async def test_1b_the_prompt_searches_per_candidate_instead_of_listing_everything(mcp_server):  # noqa: F811
    """The first real run asked for 25 requirements and got 72,858 characters back, which the client refused."""
    text = (await get_prompt(mcp_server, RECONCILE_REQUIREMENTS)).messages[0].content.text

    assert "search_text" in text
    assert text.index("search_text") < text.index("Ask for it whole"), "search before listing"
    assert "Do not open by listing the whole set" in text
    # Making the set fit by dropping Validated requirements is the tempting wrong answer: the ones most likely to
    # cover a candidate are the ones already built.
    assert "Do not filter by status to make it fit" in text


async def test_2_an_amendment_lands_through_update_rather_than_a_second_record(mcp_server):  # noqa: F811
    text = (await get_prompt(mcp_server, RECONCILE_REQUIREMENTS)).messages[0].content.text

    assert "update_requirement" in text
    assert "Never create a second record" in text


async def test_3_a_contradiction_is_reported_and_not_resolved(mcp_server):  # noqa: F811
    text = (await get_prompt(mcp_server, RECONCILE_REQUIREMENTS)).messages[0].content.text

    assert "Resolving a contradiction is the reader's decision" in text
    assert "can disagree with the code" in text


async def test_4_a_derived_requirement_is_distinguishable_in_details_and_export(mcp_server, tmp_path):  # noqa: F811
    derived = await create(mcp_server, DERIVED)
    stated = await create(mcp_server, STATED)

    assert "- **Origin**: derived-from-code" in await details(mcp_server, derived)
    assert "**Origin**" not in await details(mcp_server, stated)

    exported = await exported_requirements(mcp_server, tmp_path)
    assert "- **Origin**: derived-from-code" in exported
    assert exported.count("**Origin**") == 1, "a stated requirement gains no line"


async def test_5_a_derived_requirement_starts_in_draft_like_any_other(mcp_server):  # noqa: F811
    derived = await create(mcp_server, DERIVED)

    report = await details(mcp_server, derived)

    assert "- **Status**: Draft" in report


async def test_6_a_wrong_origin_is_correctable_like_any_other_field(mcp_server):  # noqa: F811
    derived = await create(mcp_server, DERIVED)

    fixed = await call(
        mcp_server, "update_requirement", {"requirement_id": derived, "origin": "derived-from-transcript"}
    )

    assert not fixed.isError, text_of(fixed)
    assert fixed.structuredContent["changed"] == ["origin"]
    assert "- **Origin**: derived-from-transcript" in await details(mcp_server, derived)


async def test_7_an_origin_the_server_does_not_know_is_refused_with_the_ones_it_knows(mcp_server):  # noqa: F811
    refused = await call(mcp_server, "create_requirement", {**STATED, "origin": "vibes"})

    assert refused.isError
    # The refusal names the values that would have worked. It does not name the parameter: R19 names a parameter only
    # for a type error with a close-named sibling, and an enum refusal carries jsonschema's own message. The call log
    # records the parameter either way (_rejected_field), so the gap is in the message, not in what the server knows.
    assert "derived-from-code" in text_of(refused)


async def test_8_the_source_text_is_carried_into_the_prompt(mcp_server):  # noqa: F811
    result = await get_prompt(
        mcp_server, RECONCILE_REQUIREMENTS, {"source": "we also need export to resume", "source_kind": "transcript"}
    )

    text = result.messages[0].content.text
    assert "we also need export to resume" in text
    assert "The source is: transcript" in text


async def test_9_reconciling_adds_no_tool_to_the_surface(mcp_server):  # noqa: F811
    from .test_strict_tool_inputs import listed_tools

    names = {tool.name for tool in await listed_tools(mcp_server)}
    prompts = {prompt.name for prompt in await list_prompts(mcp_server)}

    assert prompts == {CAPTURE_REQUIREMENT, RECONCILE_REQUIREMENTS}
    assert not {name for name in names if "reconcile" in name}, "reconciliation is a prompt, not a tool"
