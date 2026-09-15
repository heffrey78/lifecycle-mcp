"""get_details shows design links: implementing tasks, implemented decisions and supersession (roadmap R9)."""

from .test_design_links import link, new_decision
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def details(server, entity_id: str) -> str:
    result = await call(server, "get_details", {"entity_id": entity_id})
    assert not result.isError, text_of(result)
    return text_of(result)


async def test_details_show_implementing_tasks_and_supersession_from_both_sides(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    newer = await new_decision(mcp_server, ids["requirement"])
    assert not (await link(mcp_server, ids["task"], newer, "implements")).isError
    assert not (await link(mcp_server, newer, ids["adr"], "supersedes")).isError

    older = await details(mcp_server, ids["adr"])
    assert f"- **Superseded By**: {newer}" in older
    assert "## Implemented By" not in older and "## Supersedes" not in older

    replacement = await details(mcp_server, newer)
    assert f"## Implemented By (1)\n- {ids['task']}: Build index [Not Started]" in replacement
    assert f"## Supersedes (1)\n- {ids['adr']}: Use FTS5 [Superseded]" in replacement
    assert "**Superseded By**" not in replacement

    task = await details(mcp_server, ids["task"])
    assert f"## Implements Decisions (1)\n- {newer}: Use trigrams [Proposed]" in task


async def test_details_without_design_links_have_no_empty_sections(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    decision = await details(mcp_server, ids["adr"])
    task = await details(mcp_server, ids["task"])

    assert "Implemented By" not in decision and "Supersedes" not in decision and "Superseded By" not in decision
    assert "Implements Decisions" not in task
