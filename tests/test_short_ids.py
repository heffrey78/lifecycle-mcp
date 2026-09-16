"""Short record IDs resolve wherever a tool takes an ID (roadmap R14, TASK-0064)."""

from .test_design_links import new_decision
from .test_next_tasks import add_task
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def details(server, entity_id: str):
    return await call(server, "get_details", {"entity_id": entity_id})


async def test_each_short_form_finds_the_same_record_as_the_full_id(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    child = await call(
        mcp_server,
        "create_task",
        {
            "requirement_ids": ["REQ-1-FUNC"],  # the requirement, by alias
            "title": "Index writer",
            "priority": "P2",
            "parent_task_id": "TASK-1",  # the parent task, by alias
        },
    )
    assert not child.isError, text_of(child)

    for alias, expected in (
        ("REQ-1-FUNC", ids["requirement"]),
        ("REQ-0001-FUNC", ids["requirement"]),
        ("TASK-1", ids["task"]),
        ("TASK-1-1", child.structuredContent["id"]),
        ("ADR-1", ids["adr"]),
    ):
        found = await details(mcp_server, alias)
        assert not found.isError, f"{alias}: {text_of(found)}"
        assert expected in text_of(found), alias


async def test_full_ids_still_work_unchanged(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    for stored in (ids["requirement"], ids["task"], ids["adr"]):
        found = await details(mcp_server, stored)
        assert not found.isError and stored in text_of(found)


async def test_an_unknown_alias_is_refused(mcp_server):  # noqa: F811
    await populate(mcp_server)

    result = await details(mcp_server, "REQ-99-FUNC")

    assert result.isError is True and "No record matches REQ-99-FUNC" in text_of(result)


async def test_an_ambiguous_alias_names_the_candidates(mcp_server):  # noqa: F811
    await populate(mcp_server)  # REQ-0001-FUNC-00
    other = await call(mcp_server, "create_requirement", {**REQUIREMENT, "type": "TECH", "title": "Storage budget"})
    assert not other.isError, text_of(other)

    result = await details(mcp_server, "REQ-1")

    assert result.isError is True
    message = text_of(result)
    assert "REQ-1 matches" in message and "REQ-0001-FUNC-00" in message and "REQ-0001-TECH-00" in message


async def test_aliases_work_through_the_other_tool_families(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    newer = await new_decision(mcp_server, ids["requirement"])
    await add_task(mcp_server, ids["requirement"], "Ranking", "P2")

    moved = await call(mcp_server, "update_task_status", {"task_ids": ["TASK-1", "TASK-2"], "new_status": "Blocked"})
    assert not moved.isError, text_of(moved)
    assert moved.structuredContent["moved"] == 2

    linked = await call(
        mcp_server,
        "create_relationship",
        {"source_id": "TASK-1", "target_id": "ADR-2", "relationship_type": "implements"},
    )
    assert not linked.isError, text_of(linked)
    assert newer in text_of(await details(mcp_server, "TASK-1"))

    edit = {"requirement_id": "REQ-1-FUNC", "title": "Searchable notes", "reason": "Approved, so a reason is needed"}
    edited = await call(mcp_server, "update_requirement", edit)
    assert not edited.isError, text_of(edited)

    traced = await call(mcp_server, "trace_requirement", {"requirement_id": "REQ-1-FUNC"})
    assert not traced.isError and ids["requirement"] in text_of(traced)

    history = await call(mcp_server, "get_entity_history", {"entity_id": "ADR-1"})
    assert not history.isError and ids["adr"] in text_of(history)
