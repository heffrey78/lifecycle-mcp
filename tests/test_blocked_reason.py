"""A task keeps the reason it is blocked (roadmap R7, TASK-0052)."""

import sqlite3

from lifecycle_mcp.migrations import apply_all_migrations

from .test_migrations import SEED, database_at
from .test_next_tasks import add_task, move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


def blocked_reason(server, task_id: str) -> str | None:
    with sqlite3.connect(server.db_manager.db_path) as conn:
        return conn.execute("SELECT blocked_reason FROM tasks WHERE id = ?", [task_id]).fetchone()[0]


async def details(server, task_id: str) -> str:
    return text_of(await call(server, "get_details", {"entity_id": task_id}))


async def test_the_comment_on_a_move_to_blocked_is_kept_until_the_task_leaves_blocked(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    task = ids["task"]

    await move(mcp_server, task, "Blocked", comment="Waiting for the FTS5 build flag")
    assert blocked_reason(mcp_server, task) == "Waiting for the FTS5 build flag"
    assert "- **Blocked Reason**: Waiting for the FTS5 build flag" in await details(mcp_server, task)

    await move(mcp_server, task, "Blocked")  # staying Blocked without a comment keeps the reason
    assert blocked_reason(mcp_server, task) == "Waiting for the FTS5 build flag"
    await move(mcp_server, task, "Blocked", comment="Flag available; waiting for review")
    assert blocked_reason(mcp_server, task) == "Flag available; waiting for review"

    await move(mcp_server, task, "In Progress", comment="Unblocked")
    assert blocked_reason(mcp_server, task) is None
    assert "Blocked Reason" not in await details(mcp_server, task)


async def test_a_list_move_to_blocked_keeps_the_reason_on_each_and_a_missing_one_is_named(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    other = await add_task(mcp_server, ids["requirement"], "Rank results", "P2")

    moved = await call(
        mcp_server,
        "update_task_status",
        {"task_ids": [ids["task"], other], "new_status": "Blocked", "comment": "Design review pending"},
    )

    assert moved.structuredContent["moved"] == 2
    assert blocked_reason(mcp_server, ids["task"]) == blocked_reason(mcp_server, other) == "Design review pending"
    await move(mcp_server, other, "In Progress")
    await move(mcp_server, other, "Blocked")
    assert "- **Blocked Reason**: Not given" in await details(mcp_server, other)


def test_migration_15_adds_blocked_reason_to_existing_tasks(tmp_path):
    db = database_at(tmp_path / "blocked.db", version=14)
    with sqlite3.connect(db) as conn:
        conn.executescript(SEED)

    apply_all_migrations(db)

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, status, blocked_reason FROM tasks ORDER BY id").fetchall() == [
            ("TASK-0001-00-00", "In Progress", None),
            ("TASK-0001-01-00", "Complete", None),
            ("TASK-0002-00-00", "Not Started", None),
        ]
