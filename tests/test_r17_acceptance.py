"""R17 acceptance: each acceptance criterion of REQ-0010-FUNC-00 (signals worth trusting on the dashboard) through
the MCP server layer, one test per criterion in the requirement's order.

A signal has to fire when it carries information and stay quiet otherwise: a record written seconds ago is not
suspect, and a requirement whose work is finished is the next thing needing a decision.
"""

import re

from lifecycle_mcp.rules import STALE_AFTER_ENV_FLAG

from .test_staleness import dashboard, details, new_requirement
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)

TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

# Everything that records when a requirement was written, changed or checked.
AGEING_SQL = (
    "UPDATE requirements SET created_at = datetime(created_at, ?) WHERE id = ?",
    "UPDATE lifecycle_events SET occurred_at = datetime(occurred_at, ?) "
    "WHERE entity_type = 'requirement' AND entity_id = ?",
    "UPDATE reviews SET created_at = datetime(created_at, ?) WHERE entity_type = 'requirement' AND entity_id = ?",
)


async def age(server, requirement_id: str, days: int) -> None:
    """Move everything recorded about a requirement back in time, so it can be left unchecked for days."""
    for sql in AGEING_SQL:
        server.db_manager.execute_query(sql, [f"-{days} days", requirement_id])


async def complete(server, task_id: str) -> None:
    result = await call(server, "update_task_status", {"task_id": task_id, "new_status": "Complete"})
    assert not result.isError, text_of(result)


def line_with(text: str, marker: str) -> str:
    return next(line for line in text.splitlines() if marker in line)


async def test_1_a_requirement_left_alone_since_it_was_written_is_not_chased(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)

    shown = await details(mcp_server, requirement)
    assert "**Last Verified**" in shown and "Never verified" not in shown
    assert "Needs Verification" not in await dashboard(mcp_server)


async def test_2_a_requirement_past_the_threshold_is_listed_with_its_age(mcp_server, monkeypatch):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    await age(mcp_server, requirement, 40)

    listed = await dashboard(mcp_server)
    assert "Needs Verification (1)" in listed and "⚠️ 1 needing verification" in listed
    entry = line_with(listed, requirement)
    assert "40 days ago" in entry and "unchanged since" in entry
    assert "**⚠️ Not Verified Recently**" in await details(mcp_server, requirement)

    # The threshold is the project's to set: at 90 days the same requirement is still fresh.
    monkeypatch.setenv(STALE_AFTER_ENV_FLAG, "90")
    assert "Needs Verification" not in await dashboard(mcp_server)


async def test_3_a_stale_requirement_gives_both_times_and_invents_no_third(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    edited = await call(
        mcp_server, "update_requirement", {"requirement_id": requirement, "current_state": "Now it is indexed"}
    )
    assert not edited.isError, text_of(edited)

    entry = line_with(await details(mcp_server, requirement), "Not Verified Since It Changed")
    assert "content changed" in entry and "last checked" in entry
    assert len(TIMESTAMP.findall(entry)) == 2  # the two facts it holds, and no invented "stale since"
    assert "Stale since" not in await details(mcp_server, requirement)


async def test_4_the_changed_since_review_line_carries_the_time_of_the_edit(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)  # leaves the requirement Approved

    edited = await call(
        mcp_server,
        "update_requirement",
        {"requirement_id": ids["requirement"], "current_state": "Search runs unindexed", "reason": "Measured again"},
    )
    assert not edited.isError, text_of(edited)

    entry = line_with(await details(mcp_server, ids["requirement"]), "Changed Since Last Review")
    assert TIMESTAMP.search(entry) and "while Approved" in entry
    assert TIMESTAMP.search(line_with(await dashboard(mcp_server), "current_state"))


async def test_5_a_validated_requirement_edited_in_place_shows_both_warnings(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await complete(mcp_server, ids["task"])
    moved = await call(
        mcp_server, "update_requirement_status", {"requirement_id": ids["requirement"], "new_status": "Validated"}
    )
    assert not moved.isError, text_of(moved)

    edited = await call(
        mcp_server,
        "update_requirement",
        {"requirement_id": ids["requirement"], "desired_state": "Ranked search over 10k notes", "reason": "Re-scoped"},
    )
    assert not edited.isError, text_of(edited)

    shown = await details(mcp_server, ids["requirement"])
    assert "**⚠️ Not Verified Since It Changed**" in shown and "**⚠️ Changed Since Last Review**" in shown

    commented = await call(
        mcp_server, "add_comment", {"entity_id": ids["requirement"], "comment": "Re-read against the code"}
    )
    assert not commented.isError, text_of(commented)

    after = await details(mcp_server, ids["requirement"])
    assert "Not Verified Since It Changed" not in after  # a comment marks it checked
    assert "**⚠️ Changed Since Last Review**" in after  # but the review it never went back through still stands


async def test_6_a_project_whose_work_is_done_names_the_requirements_awaiting_a_decision(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    assert "Work Complete" not in await dashboard(mcp_server)  # the task is still Not Started

    await complete(mcp_server, ids["task"])

    listed = await dashboard(mcp_server)
    assert "Work Complete, Decision Pending (1)" in listed and "🏁 1 awaiting a decision" in listed
    entry = line_with(listed, ids["requirement"])
    assert "[Approved]" in entry and "1 task complete" in entry
    assert "**Requirements Completion**: 0.0%" in listed  # still true, and no longer the only thing said


async def test_7_query_requirements_finds_exactly_the_requirements_whose_work_is_done(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await new_requirement(mcp_server, title="Nothing planned yet")

    waiting = await call(mcp_server, "query_requirements", {"work_complete": True})
    assert waiting.structuredContent == {"requirements": [], "count": 0}

    await complete(mcp_server, ids["task"])

    done = await call(mcp_server, "query_requirements", {"work_complete": True})
    assert [found["id"] for found in done.structuredContent["requirements"]] == [ids["requirement"]]
    assert "work complete, decision pending" in text_of(done)


async def test_8_an_empty_ready_result_says_which_case_it_is(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    blocked = await call(mcp_server, "update_task_status", {"task_id": ids["task"], "new_status": "Blocked"})
    assert not blocked.isError, text_of(blocked)
    waiting = text_of(await call(mcp_server, "query_tasks", {"ready": True}))
    assert "No tasks ready to start" in waiting and "Every remaining task is waiting: 1 Blocked" in waiting

    await call(mcp_server, "update_task_status", {"task_id": ids["task"], "new_status": "In Progress"})
    under_way = text_of(await call(mcp_server, "query_tasks", {"ready": True}))
    assert "No tasks ready to start" in under_way and "1 task(s) already In Progress" in under_way

    await complete(mcp_server, ids["task"])
    finished = text_of(await call(mcp_server, "query_tasks", {"ready": True}))
    assert "No tasks remain: every task is Complete or Abandoned" in finished
