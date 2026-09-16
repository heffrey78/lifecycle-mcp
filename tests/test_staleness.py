"""A requirement shows when it was last checked against reality (roadmap R11, TASK-0072)."""

import time

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


async def test_a_requirement_nobody_has_touched_says_it_was_never_verified(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)

    assert "**⚠️ Never verified**" in await details(mcp_server, requirement)
    listed = await dashboard(mcp_server)
    assert "Not Verified Since Last Change (1)" in listed
    assert f"{requirement}" in listed and "last checked never" in listed


async def test_a_comment_marks_it_checked(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)

    added = await call(
        mcp_server, "add_comment", {"entity_id": requirement, "comment": "Still matches the code", "author": "jeff"}
    )
    assert not added.isError, text_of(added)

    shown = await details(mcp_server, requirement)
    assert "**Last Verified**" in shown and "Never verified" not in shown
    assert "Not Verified Since Last Change" not in await dashboard(mcp_server)


async def test_a_status_move_marks_it_checked_too(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)

    moved = await call(
        mcp_server, "update_requirement_status", {"requirement_id": requirement, "new_status": "Under Review"}
    )
    assert not moved.isError, text_of(moved)

    assert "**Last Verified**" in await details(mcp_server, requirement)


async def test_changing_the_content_afterwards_makes_it_stale_again(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    await call(mcp_server, "add_comment", {"entity_id": requirement, "comment": "Checked against the code"})
    # Comment times are second-resolution, so the edit has to land in a later second to be unambiguously after it.
    time.sleep(1.1)

    edited = await call(
        mcp_server,
        "update_requirement",
        {"requirement_id": requirement, "current_state": "The index is rebuilt on every save"},
    )
    assert not edited.isError, text_of(edited)

    shown = await details(mcp_server, requirement)
    assert "**⚠️ Stale since**" in shown
    assert "a comment or status change marks it checked" in shown
    listed = await dashboard(mcp_server)
    assert "Not Verified Since Last Change (1)" in listed and "⚠️ 1 not verified since changing" in listed


async def test_a_deprecated_requirement_is_not_chased(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    await call(mcp_server, "update_requirement_status", {"requirement_id": requirement, "new_status": "Deprecated"})

    assert "Not Verified Since Last Change" not in await dashboard(mcp_server)
