"""A task's parent link is refused by naming the tool that makes one (REQ-0007-INTF-00, TASK-0099).

The refusal used to read "Invalid relationship: task -> task (parent)", which was false twice over: the link is valid,
and the server creates it in two places. What is true is that create_relationship does not make it, because
re-parenting has to go through _apply_edit to be recorded in the task's history. R19's rule applies - an error names
what would have worked.
"""

from .test_next_tasks import add_task
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def two_tasks(server) -> tuple[str, str]:
    ids = await populate(server)
    return ids["task"], await add_task(server, ids["requirement"], "Cache layer", "P2")


async def test_the_refusal_names_update_task_and_its_parameter(mcp_server):  # noqa: F811
    parent, child = await two_tasks(mcp_server)

    result = await call(
        mcp_server, "create_relationship", {"source_id": child, "target_id": parent, "relationship_type": "parent"}
    )

    assert result.isError
    assert "update_task" in text_of(result) and "parent_task_id" in text_of(result)
    assert "invalid" not in text_of(result).lower(), text_of(result)


async def test_the_reversed_request_gets_the_same_refusal(mcp_server):  # noqa: F811
    """Direction is normalized after validation, so both orders are one pair and get one message."""
    parent, child = await two_tasks(mcp_server)

    forwards = await call(
        mcp_server, "create_relationship", {"source_id": child, "target_id": parent, "relationship_type": "parent"}
    )
    backwards = await call(
        mcp_server, "create_relationship", {"source_id": parent, "target_id": child, "relationship_type": "parent"}
    )

    assert forwards.isError and backwards.isError
    assert "update_task" in text_of(backwards)


async def test_a_pair_that_cannot_exist_is_still_called_invalid(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    result = await call(
        mcp_server,
        "create_relationship",
        {"source_id": ids["requirement"], "target_id": ids["task"], "relationship_type": "supersedes"},
    )

    assert result.isError
    assert "Invalid relationship" in text_of(result), "a link the server never makes is still invalid"


async def test_update_task_still_makes_the_link_and_records_it(mcp_server):  # noqa: F811
    parent, child = await two_tasks(mcp_server)

    moved = await call(mcp_server, "update_task", {"task_id": child, "parent_task_id": parent})

    assert not moved.isError, text_of(moved)
    links = await call(mcp_server, "query_relationships", {"entity_id": child})
    assert parent in text_of(links)

    history = await call(mcp_server, "get_entity_history", {"entity_id": child})
    assert not history.isError, text_of(history)
    assert "parent" in text_of(history).lower(), "the move is in the task's history, which is why it is not a bare row"
