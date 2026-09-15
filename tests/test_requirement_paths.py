"""update_requirement_status walks the allowed path, never through Approved or Validated (roadmap R9, ADR-0003)."""

import sqlite3

from .test_bulk_status import create_requirements
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


def status_steps(server, entity_id: str) -> list[tuple[str, str]]:
    with sqlite3.connect(server.db_manager.db_path) as conn:
        return conn.execute(
            "SELECT from_value, to_value FROM lifecycle_events "
            "WHERE entity_id = ? AND event_type = 'status_change' ORDER BY id",
            [entity_id],
        ).fetchall()


async def move(server, requirement_id: str, new_status: str, **extra):
    return await call(
        server, "update_requirement_status", {"requirement_id": requirement_id, "new_status": new_status, **extra}
    )


async def test_approving_eight_drafts_through_review_takes_one_call(mcp_server):  # noqa: F811
    ids = await create_requirements(mcp_server, 8)

    result = await call(
        mcp_server,
        "update_requirement_status",
        {"requirement_ids": ids, "new_status": "Approved", "comment": "Reviewed together"},
    )

    assert text_of(result).startswith("[SUCCESS] Moved 8 of 8 requirements to Approved")
    assert f"- {ids[0]}: Draft → Under Review → Approved" in text_of(result)
    for entry, requirement_id in zip(result.structuredContent["results"], ids, strict=True):
        assert entry == {
            "id": requirement_id,
            "from_status": "Draft",
            "to_status": "Approved",
            "path": ["Draft", "Under Review", "Approved"],
        }
        assert status_steps(mcp_server, requirement_id) == [("Draft", "Under Review"), ("Under Review", "Approved")]
        details = text_of(await call(mcp_server, "get_details", {"entity_id": requirement_id}))
        assert details.count("Reviewed together") == 1


async def test_approved_to_validated_in_one_call_shows_the_path(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await call(mcp_server, "update_task_status", {"task_id": ids["task"], "new_status": "Complete"})

    result = await move(mcp_server, ids["requirement"], "Validated")

    assert text_of(result) == (
        f"[SUCCESS] Requirement {ids['requirement']} updated\n📈 Approved → Ready → Implemented → Validated"
    )
    assert result.structuredContent["path"] == ["Approved", "Ready", "Implemented", "Validated"]


async def test_one_step_results_are_unchanged(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    result = await move(mcp_server, ids["requirement"], "Ready")

    assert result.structuredContent == {"id": ids["requirement"], "from_status": "Approved", "to_status": "Ready"}


async def test_a_gate_on_the_way_refuses_the_whole_move(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    assert not (await move(mcp_server, ids["requirement"], "Ready")).isError

    result = await move(mcp_server, ids["requirement"], "Validated", comment="Should not be kept")

    assert result.isError and "Cannot validate requirement with incomplete tasks" in text_of(result)
    details = text_of(await call(mcp_server, "get_details", {"entity_id": ids["requirement"]}))
    assert "**Status**: Ready" in details and "Should not be kept" not in details
    assert status_steps(mcp_server, ids["requirement"])[-1] == ("Approved", "Ready")


async def test_a_move_never_passes_through_approved(mcp_server):  # noqa: F811
    [draft] = await create_requirements(mcp_server, 1)

    result = await move(mcp_server, draft, "Ready")

    assert result.isError
    assert "Invalid transition from Draft to Ready in one call: it would pass through Approved" in text_of(result)
    assert "Move it to Approved first" in text_of(result)
    assert status_steps(mcp_server, draft) == []


async def test_a_move_to_deprecated_goes_around_validated(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    assert not (await move(mcp_server, ids["requirement"], "Implemented")).isError

    result = await move(mcp_server, ids["requirement"], "Deprecated")

    assert result.structuredContent["path"] == ["Implemented", "Ready", "Deprecated"]


async def test_no_allowed_path_names_the_next_statuses(mcp_server):  # noqa: F811
    [draft] = await create_requirements(mcp_server, 1)
    assert not (await move(mcp_server, draft, "Deprecated")).isError

    result = await move(mcp_server, draft, "Draft")

    assert result.isError
    assert "Invalid transition from Deprecated to Draft. From Deprecated it can move to: nothing" in text_of(result)
