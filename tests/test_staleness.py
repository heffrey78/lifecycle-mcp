"""A requirement shows when it was last checked against reality (roadmap R11, TASK-0072).

Writing a requirement starts its verification clock, so a record nobody has touched since is fresh rather than
suspect; it goes stale when its content changes after the last check, or when it ages past the threshold (R17).
"""

import asyncio

from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)


async def details(server, requirement_id: str) -> str:
    result = await call(server, "get_details", {"entity_id": requirement_id})
    assert not result.isError, text_of(result)
    return text_of(result)


async def dashboard(server) -> str:
    result = await call(server, "get_project_status", {})
    assert not result.isError, text_of(result)
    return text_of(result)


async def new_requirement(server, **overrides) -> str:
    result = await call(server, "create_requirement", {**REQUIREMENT, **overrides})
    assert not result.isError, text_of(result)
    return result.structuredContent["id"]


async def test_writing_a_requirement_counts_as_checking_it(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)

    shown = await details(mcp_server, requirement)
    assert "**Last Verified**" in shown and "less than a day ago" in shown
    assert "Never verified" not in shown
    assert "Needs Verification" not in await dashboard(mcp_server)


async def test_a_comment_marks_a_changed_requirement_checked_again(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    edited = await call(
        mcp_server, "update_requirement", {"requirement_id": requirement, "current_state": "The index is rebuilt"}
    )
    assert not edited.isError, text_of(edited)
    assert "**⚠️ Not Verified Since It Changed**" in await details(mcp_server, requirement)

    added = await call(
        mcp_server, "add_comment", {"entity_id": requirement, "comment": "Still matches the code", "author": "jeff"}
    )
    assert not added.isError, text_of(added)

    shown = await details(mcp_server, requirement)
    assert "**Last Verified**" in shown and "Not Verified" not in shown
    assert "Needs Verification" not in await dashboard(mcp_server)


async def test_a_status_move_marks_it_checked_too(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    await call(mcp_server, "update_requirement", {"requirement_id": requirement, "current_state": "Rebuilt on save"})

    moved = await call(
        mcp_server, "update_requirement_status", {"requirement_id": requirement, "new_status": "Under Review"}
    )
    assert not moved.isError, text_of(moved)

    assert "**Last Verified**" in await details(mcp_server, requirement)


async def test_changing_the_content_afterwards_makes_it_stale_again(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    await call(mcp_server, "add_comment", {"entity_id": requirement, "comment": "Checked against the code"})
    # Comment times are second-resolution, so the edit has to land in a later second to be unambiguously after it.
    await asyncio.sleep(1.1)

    edited = await call(
        mcp_server,
        "update_requirement",
        {"requirement_id": requirement, "current_state": "The index is rebuilt on every save"},
    )
    assert not edited.isError, text_of(edited)

    shown = await details(mcp_server, requirement)
    assert "**⚠️ Not Verified Since It Changed**" in shown
    assert "a comment or status change marks it checked" in shown
    listed = await dashboard(mcp_server)
    assert "Needs Verification (1)" in listed and "⚠️ 1 needing verification" in listed


async def test_a_deprecated_requirement_is_not_chased(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    await call(mcp_server, "update_requirement", {"requirement_id": requirement, "current_state": "Rebuilt on save"})
    await call(mcp_server, "update_requirement_status", {"requirement_id": requirement, "new_status": "Deprecated"})

    assert "Needs Verification" not in await dashboard(mcp_server)
