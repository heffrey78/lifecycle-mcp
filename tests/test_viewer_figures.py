"""The viewer's figures are the server's figures (REQ-0006-INTF-00, TASK-0091).

The risk this guards is a second definition of "work complete" or "stale" living in the viewer, disagreeing with the
dashboard about the same record, and leaving a reader no way to tell which is right. So the figures are compared with
what get_project_status and query_tasks actually report, and a test reads the viewer's source to check it imports the
definitions rather than restating their SQL.
"""

import re
from pathlib import Path

from lifecycle_mcp.rules import STALE_AFTER_ENV_FLAG
from lifecycle_mcp.viewer.figures import derive_figures
from lifecycle_mcp.viewer.snapshot import ReadOnlyDatabase, read_snapshot

from .test_next_tasks import add_task, link, move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)
from .test_viewer_snapshot import db_path

VIEWER = Path(__file__).resolve().parent.parent / "src" / "lifecycle_mcp" / "viewer"


def figures_for(server):
    path = db_path(server)
    return derive_figures(read_snapshot(path), ReadOnlyDatabase(path))


async def status_payload(server) -> dict:
    result = await call(server, "get_project_status", {"include_blocked": True})
    assert not result.isError, text_of(result)
    return result.structuredContent


async def test_the_counts_match_the_dashboard(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await add_task(mcp_server, ids["requirement"], "Cache layer", "P0")

    figures = figures_for(mcp_server)
    payload = await status_payload(mcp_server)

    assert figures.requirements_by_status == payload["requirements"]["by_status"]
    assert figures.requirements_by_priority == payload["requirements"]["by_priority"]
    assert figures.tasks_by_status == payload["tasks"]["by_status"]
    assert figures.tasks_by_priority == payload["tasks"]["by_priority"]
    assert figures.architecture_by_status == payload["architecture"]["by_status"]


async def test_blocked_work_matches_the_dashboard(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    waiting = await add_task(mcp_server, ids["requirement"], "API", "P1")
    await link(mcp_server, waiting, ids["task"], "depends")

    figures = figures_for(mcp_server)
    payload = await status_payload(mcp_server)

    assert [row["id"] for row in figures.blocked] == [item["id"] for item in payload["blocked"]]
    entry = next(row for row in figures.blocked if row["id"] == waiting)
    assert entry["waiting_on"] == [ids["task"]]


async def test_work_complete_matches_the_dashboard_and_the_filter(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Complete")

    figures = figures_for(mcp_server)
    payload = await status_payload(mcp_server)
    filtered = await call(mcp_server, "query_requirements", {"work_complete": True})

    assert [row["id"] for row in figures.work_complete] == payload["requirements"]["work_complete"]
    assert [row["id"] for row in figures.work_complete] == [r["id"] for r in filtered.structuredContent["requirements"]]
    assert figures.work_complete, "one complete task and no open ones is the case this section is for"


async def test_ready_to_start_matches_the_tool(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    waiting = await add_task(mcp_server, ids["requirement"], "API", "P1")
    await link(mcp_server, waiting, ids["task"], "depends")

    figures = figures_for(mcp_server)
    tool = await call(mcp_server, "query_tasks", {"ready": True})

    assert [row["id"] for row in figures.ready] == [t["id"] for t in tool.structuredContent["tasks"]]
    assert waiting not in [row["id"] for row in figures.ready], "it waits on an unfinished task"


async def test_staleness_matches_the_dashboard_and_honours_the_threshold(mcp_server, monkeypatch):  # noqa: F811
    ids = await populate(mcp_server)
    assert not (
        await call(
            mcp_server,
            "update_requirement",
            {"requirement_id": ids["requirement"], "title": "Edited", "reason": "sharpening the title"},
        )
    ).isError

    # A requirement written and edited today is stale only because its content changed after its last check.
    figures = figures_for(mcp_server)
    assert [row["id"] for row in figures.stale] == [ids["requirement"]]
    assert figures.stale[0]["stale_reason"] == "changed"
    assert figures.stale[0]["age"], "the dashboard's own phrasing for how long ago"

    # A huge threshold cannot clear a changed requirement, but it is the flag the server reads.
    monkeypatch.setenv(STALE_AFTER_ENV_FLAG, "99999")
    assert [row["id"] for row in figures_for(mcp_server).stale] == [ids["requirement"]]


async def test_changed_since_review_matches_the_dashboard(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    assert not (
        await call(
            mcp_server,
            "update_requirement",
            {"requirement_id": ids["requirement"], "business_value": "restated", "reason": "review follow-up"},
        )
    ).isError

    figures = figures_for(mcp_server)

    assert [row["id"] for row in figures.changed_since_review] == [ids["requirement"]]
    assert "business_value" in figures.changed_since_review[0]["fields"]


async def test_an_empty_section_says_which_case_it_is(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    figures = figures_for(mcp_server)

    # One Not Started task with no dependencies: it is ready, so that section is not empty.
    assert [row["id"] for row in figures.ready] == [ids["task"]]
    assert "ready" not in figures.empty_reasons
    for section in ("blocked", "work_complete", "changed_since_review"):
        assert figures.empty_reasons[section], section
    assert "No requirement has its work finished" in figures.empty_reasons["work_complete"]


async def test_nothing_ready_distinguishes_no_work_left_from_everything_waiting(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Complete")

    finished = figures_for(mcp_server)

    assert not finished.ready
    assert "every task is Complete or Abandoned" in finished.empty_reasons["ready"]

    started = await add_task(mcp_server, ids["requirement"], "API", "P1")
    await move(mcp_server, started, "In Progress")

    under_way = figures_for(mcp_server)

    assert not under_way.ready
    assert "already under way" in under_way.empty_reasons["ready"]


def test_the_viewer_imports_the_definitions_instead_of_restating_them():
    """A copied WHERE clause is how the viewer and the dashboard would come to disagree."""
    source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(VIEWER.glob("*.py")))

    for name in ("WORK_COMPLETE_WHERE", "BLOCKED_TASKS_SQL", "READY_TASKS_WHERE", "stale_requirements"):
        assert name in source, f"{name} should be imported and used"

    # The shapes those definitions are made of, which a reimplementation would have to spell out again. Comparisons and
    # joins, not bare column names: the page lists tasks_completed among the fields it displays, and naming a column in
    # order to show it is not restating the rule that reads it.
    for copied in (
        "tasks_completed >=",
        "relationship_type = 'depends'",
        "relationship_type = 'implements'",
        "status = 'Blocked'",
        "NOT IN ('Complete'",
    ):
        assert copied not in source, f"{copied!r} looks like a copy of a definition the handlers own"


def test_no_figure_is_computed_from_a_hand_written_status_list():
    """The tallies may count rows; the judgements may not invent their own criteria."""
    figures_source = (VIEWER / "figures.py").read_text(encoding="utf-8")
    judgement_sql = re.findall(r"SELECT .*?FROM requirements.*?WHERE", figures_source, re.IGNORECASE | re.DOTALL)

    for statement in judgement_sql:
        assert "WORK_COMPLETE_WHERE" in figures_source, statement
