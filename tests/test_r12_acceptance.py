"""R12 acceptance: each acceptance criterion of REQ-0007-FUNC-00 (evidence and decision records on tasks) through
the MCP server layer, one test per criterion in the requirement's order (TASK-0069).
"""

from .test_evidence import export, move, stored
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def test_1_completing_a_task_with_a_commit_and_a_test_summary_shows_both(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "In Progress")

    await move(mcp_server, ids["task"], "Complete", commit="a1b2c3d", evidence="331 passed, coverage 72%")

    shown = text_of(await call(mcp_server, "get_details", {"entity_id": ids["task"]}))
    assert "- **Commit**: a1b2c3d" in shown
    assert "- **Evidence**: 331 passed, coverage 72%" in shown


async def test_2_the_exported_task_documentation_contains_them(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Complete", commit="a1b2c3d", evidence="331 passed, coverage 72%")

    exported = await export(mcp_server, tmp_path)

    assert "a1b2c3d" in exported["tasks"] and "331 passed, coverage 72%" in exported["tasks"]


async def test_3_the_exported_documentation_contains_comments(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    added = await call(
        mcp_server,
        "add_comment",
        {"entity_id": ids["task"], "comment": "Ranked search verified at 26 ms p95", "author": "jeff"},
    )
    assert not added.isError, text_of(added)

    exported = await export(mcp_server, tmp_path)

    assert "Ranked search verified at 26 ms p95" in exported["tasks"]


async def test_4_a_later_move_without_them_keeps_what_was_recorded(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Complete", commit="a1b2c3d", evidence="331 passed")

    await move(mcp_server, ids["task"], "In Progress", comment="Reopened to fix a regression")

    assert stored(mcp_server, ids["task"]) == ("a1b2c3d", "331 passed")
