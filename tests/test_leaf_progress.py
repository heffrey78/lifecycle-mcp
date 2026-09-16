"""Requirement progress counts leaf tasks, not a parent and its subtasks both (roadmap R14, TASK-0065)."""

import sqlite3

from lifecycle_mcp.migrations import apply_all_migrations

from .test_migrations import SEED, database_at
from .test_next_tasks import move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


def counters(server, requirement_id: str) -> tuple[int, int]:
    with sqlite3.connect(server.db_manager.db_path) as conn:
        return conn.execute(
            "SELECT task_count, tasks_completed FROM requirements WHERE id = ?", [requirement_id]
        ).fetchone()


async def subtask_of(server, requirement_id: str, parent_id: str, title: str) -> str:
    arguments = {"requirement_ids": [requirement_id], "title": title, "priority": "P2", "parent_task_id": parent_id}
    result = await call(server, "create_task", arguments)
    assert not result.isError, text_of(result)
    return result.structuredContent["id"]


async def test_a_task_split_in_two_counts_as_its_two_leaves(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    assert counters(mcp_server, ids["requirement"]) == (1, 0)

    first = await subtask_of(mcp_server, ids["requirement"], ids["task"], "Index writer")
    second = await subtask_of(mcp_server, ids["requirement"], ids["task"], "Index reader")

    # The parent stops being a leaf as soon as it has subtasks: two tasks of work, not three.
    assert counters(mcp_server, ids["requirement"]) == (2, 0)

    await move(mcp_server, first, "Complete")
    assert counters(mcp_server, ids["requirement"]) == (2, 1)
    await move(mcp_server, second, "Complete")
    assert counters(mcp_server, ids["requirement"]) == (2, 2)

    details = text_of(await call(mcp_server, "get_details", {"entity_id": ids["requirement"]}))
    assert "2" in details  # the requirement reports two tasks of work


async def test_completing_a_parent_does_not_add_to_the_count(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    child = await subtask_of(mcp_server, ids["requirement"], ids["task"], "Index writer")
    await move(mcp_server, child, "Complete")

    await move(mcp_server, ids["task"], "Complete")

    assert counters(mcp_server, ids["requirement"]) == (1, 1)


async def test_a_requirement_without_subtasks_is_unaffected(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    await move(mcp_server, ids["task"], "Complete")

    assert counters(mcp_server, ids["requirement"]) == (1, 1)


def test_migration_16_recomputes_existing_counters_without_touching_status(tmp_path):
    db = database_at(tmp_path / "leaves.db", version=15)
    with sqlite3.connect(db) as conn:
        conn.executescript(SEED)
        conn.executescript(
            """
            INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) VALUES
                ('rel-r1-t1', 'requirement', 'REQ-0001-FUNC-00', 'task', 'TASK-0001-00-00', 'implements'),
                ('rel-r1-t1s', 'requirement', 'REQ-0001-FUNC-00', 'task', 'TASK-0001-01-00', 'implements'),
                ('rel-t1s-t1', 'task', 'TASK-0001-01-00', 'task', 'TASK-0001-00-00', 'parent');
            """
        )
        before = conn.execute(
            "SELECT task_count, tasks_completed FROM requirements WHERE id = 'REQ-0001-FUNC-00'"
        ).fetchone()
        statuses = conn.execute("SELECT id, status FROM tasks ORDER BY id").fetchall()
    assert before == (2, 1)  # the parent and its subtask were both counted

    assert apply_all_migrations(db) == 16

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT task_count, tasks_completed FROM requirements WHERE id = 'REQ-0001-FUNC-00'"
        ).fetchone() == (1, 1)  # only the subtask is a leaf, and it is Complete
        assert conn.execute("SELECT id, status FROM tasks ORDER BY id").fetchall() == statuses
