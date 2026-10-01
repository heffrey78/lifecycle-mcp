"""Abandoned work does not block validation forever (REQ-0014-FUNC-00).

Abandoning a task is how you record that work was dropped, and it used to cost the requirement its ending: the
Validated gate asked for `t.status != 'Complete'`, which an Abandoned task can never satisfy. The honest move was the
expensive one, and the cheap alternatives were deleting the link, which erases that the work was planned, or marking
abandoned work Complete, which writes a false status change into the event log that staleness then reads as evidence.

Every other part of the server already counted Complete and Abandoned together as endings. These tests pin the
requirement side to the same rule, and pin the one case that still refuses: nothing completed at all.
"""

from lifecycle_mcp.handlers.requirement_handler import (
    OPEN_TASK_STATUSES,
    VALIDATION_READY_WHERE,
    WORK_COMPLETE_WHERE,
)
from lifecycle_mcp.rules import RULES_ENV_FLAG

from .test_next_tasks import add_task, move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def validate(server, requirement_id: str):
    return await call(
        server, "update_requirement_status", {"requirement_id": requirement_id, "new_status": "Validated"}
    )


async def status_of(server, requirement_id: str) -> str:
    result = await call(server, "query_requirements", {})
    assert not result.isError, text_of(result)
    return next(r["status"] for r in result.structuredContent["requirements"] if r["id"] == requirement_id)


async def one_complete_one_abandoned(server) -> tuple[str, str]:
    """A requirement whose work has an ending: one task done, one dropped.

    Returns the requirement and the abandoned task.
    """
    ids = await populate(server)
    dropped = await add_task(server, ids["requirement"], "Cache layer", "P2")
    await move(server, ids["task"], "Complete")
    await move(server, dropped, "Abandoned")
    return ids["requirement"], dropped


# --- the definition (TASK-0096) ------------------------------------------------------------------


def test_the_open_statuses_are_the_unfinished_ones_and_exclude_both_endings():
    assert OPEN_TASK_STATUSES == ("Not Started", "In Progress", "Blocked")
    assert "Complete" not in OPEN_TASK_STATUSES and "Abandoned" not in OPEN_TASK_STATUSES


def test_work_complete_is_built_on_the_one_ready_definition():
    """The dashboard section, the work_complete filter and the gate cannot disagree if there is one definition."""
    assert WORK_COMPLETE_WHERE.startswith(VALIDATION_READY_WHERE)
    assert "task_count" not in VALIDATION_READY_WHERE, "derived from the tasks, not from a stored counter"
    assert "tasks_completed" not in VALIDATION_READY_WHERE


async def test_a_requirement_is_ready_only_with_a_completed_task_and_nothing_open(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    requirement, first = ids["requirement"], ids["task"]
    second = await add_task(mcp_server, requirement, "Cache layer", "P2")

    async def ready() -> bool:
        result = await call(mcp_server, "query_requirements", {"work_complete": True})
        assert not result.isError, text_of(result)
        return requirement in [r["id"] for r in result.structuredContent["requirements"]]

    assert not await ready(), "nothing finished yet"

    await move(mcp_server, second, "Abandoned")
    assert not await ready(), "one task still Not Started"

    await move(mcp_server, first, "Complete")
    assert await ready(), "one complete, one abandoned: the work has an ending"


async def test_a_requirement_whose_every_task_was_abandoned_is_not_work_complete(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Abandoned")

    result = await call(mcp_server, "query_requirements", {"work_complete": True})

    assert not result.isError, text_of(result)
    ids_returned = [r["id"] for r in result.structuredContent["requirements"]]
    assert ids["requirement"] not in ids_returned, "nothing was completed, so no work is complete"


async def test_a_parent_task_is_counted_through_its_subtasks(mcp_server):  # noqa: F811
    """The leaf rule has one home: the gate reads the same is-leaf condition the counter triggers use (F-22)."""
    ids = await populate(mcp_server)
    parent, requirement = ids["task"], ids["requirement"]
    created = await call(
        mcp_server,
        "create_task",
        {"requirement_ids": [requirement], "title": "Subtask", "priority": "P2", "parent_task_id": parent},
    )
    assert not created.isError, text_of(created)
    subtask = created.structuredContent["id"]

    await move(mcp_server, subtask, "Complete")
    # The parent is left Not Started: it is not a leaf, so its own status does not hold the requirement open.
    result = await call(mcp_server, "query_requirements", {"work_complete": True})

    assert requirement in [r["id"] for r in result.structuredContent["requirements"]]


# --- the Validated gate (TASK-0097) --------------------------------------------------------------


async def test_abandoned_work_no_longer_blocks_validation_and_is_named(mcp_server):  # noqa: F811
    requirement, dropped = await one_complete_one_abandoned(mcp_server)

    result = await validate(mcp_server, requirement)

    assert not result.isError, text_of(result)
    assert dropped in text_of(result)
    assert "abandoned" in text_of(result).lower()
    assert await status_of(mcp_server, requirement) == "Validated"


async def test_enforce_refuses_the_same_move_and_writes_nothing(mcp_server, monkeypatch):  # noqa: F811
    requirement, _ = await one_complete_one_abandoned(mcp_server)
    monkeypatch.setenv(RULES_ENV_FLAG, "enforce")

    result = await validate(mcp_server, requirement)

    assert result.isError
    assert "Refused by workflow rules (LIFECYCLE_RULES=enforce)" in text_of(result)
    assert await status_of(mcp_server, requirement) == "Approved", "the refusal left the status alone"


async def test_off_validates_without_mentioning_the_abandoned_task(mcp_server, monkeypatch):  # noqa: F811
    requirement, dropped = await one_complete_one_abandoned(mcp_server)
    monkeypatch.setenv(RULES_ENV_FLAG, "off")

    result = await validate(mcp_server, requirement)

    assert not result.isError, text_of(result)
    assert dropped not in text_of(result) and "⚠️" not in text_of(result)
    assert await status_of(mcp_server, requirement) == "Validated"


async def test_a_requirement_with_only_abandoned_tasks_is_refused_and_pointed_at_deprecated(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Abandoned")

    result = await validate(mcp_server, ids["requirement"])

    assert result.isError
    assert "Deprecate" in text_of(result)
    assert ids["task"] in text_of(result)
    assert await status_of(mcp_server, ids["requirement"]) == "Approved"


async def test_an_open_task_still_refuses_validation(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "In Progress")

    result = await validate(mcp_server, ids["requirement"])

    assert result.isError
    assert "Cannot validate requirement with incomplete tasks" in text_of(result)
    assert ids["task"] in text_of(result)


async def test_a_requirement_with_no_tasks_is_still_validatable(mcp_server):  # noqa: F811
    """The gate only ever refused work with no ending. No work at all has always been allowed through."""
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "Nothing to do",
            "priority": "P3",
            "current_state": "Nothing happens.",
            "desired_state": "Still nothing, deliberately.",
        },
    )
    requirement = result.structuredContent["id"]
    for status in ("Under Review", "Approved", "Ready", "Implemented"):
        assert not (
            await call(mcp_server, "update_requirement_status", {"requirement_id": requirement, "new_status": status})
        ).isError

    assert not (await validate(mcp_server, requirement)).isError


# --- the Implemented gate (TASK-0098) ------------------------------------------------------------


async def test_reaching_implemented_does_not_report_abandoned_work_as_not_complete(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    dropped = await add_task(mcp_server, ids["requirement"], "Cache layer", "P2")
    await move(mcp_server, ids["task"], "Complete")
    await move(mcp_server, dropped, "Abandoned")

    result = await call(
        mcp_server, "update_requirement_status", {"requirement_id": ids["requirement"], "new_status": "Implemented"}
    )

    assert not result.isError, text_of(result)
    assert "Tasks not Complete" not in text_of(result), "an abandoned task can never become Complete"
    assert "abandoned" in text_of(result).lower(), "it is still named, as abandoned"


async def test_an_open_task_still_warns_on_the_way_to_implemented(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    result = await call(
        mcp_server, "update_requirement_status", {"requirement_id": ids["requirement"], "new_status": "Implemented"}
    )

    assert not result.isError, text_of(result)
    assert f"Tasks not Complete: {ids['task']} (Not Started)" in text_of(result)


async def test_abandoned_work_is_warned_about_once_for_a_move_that_ends_at_validated(mcp_server):  # noqa: F811
    """Ready to Validated passes through Implemented; both gates would otherwise say the same thing (R17)."""
    requirement, dropped = await one_complete_one_abandoned(mcp_server)
    assert not (
        await call(mcp_server, "update_requirement_status", {"requirement_id": requirement, "new_status": "Ready"})
    ).isError

    result = await validate(mcp_server, requirement)

    assert not result.isError, text_of(result)
    warnings = result.structuredContent["warnings"]
    assert len([reason for reason in warnings if dropped in reason]) == 1, warnings


# --- no migration (TASK-0096) --------------------------------------------------------------------


async def test_nothing_was_migrated_for_this(mcp_server):  # noqa: F811
    """Derived, not stored: the open-work question is answered in SQL against the tasks, so there is no new column."""
    from lifecycle_mcp.migrations import MIGRATIONS

    # 18 was the newest migration when this was built; what follows it is accounted for by name.
    later = [description for _, description, _ in MIGRATIONS[18:]]
    assert later == ["Projects: groups of requirements with a stated purpose"], "REQ-0014-FUNC-00 adds no migration"
