"""A task keeps the commit and evidence behind its status (roadmap R12, TASK-0067)."""

import sqlite3

from lifecycle_mcp.migrations import apply_all_migrations

from .test_migrations import LATEST, SEED, database_at
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


def stored(server, task_id: str) -> tuple:
    with sqlite3.connect(server.db_manager.db_path) as conn:
        return conn.execute("SELECT commit_ref, evidence FROM tasks WHERE id = ?", [task_id]).fetchone()


async def move(server, task_id: str, new_status: str, **extra):
    result = await call(server, "update_task_status", {"task_id": task_id, "new_status": new_status, **extra})
    assert not result.isError, text_of(result)
    return result


async def details(server, task_id: str) -> str:
    return text_of(await call(server, "get_details", {"entity_id": task_id}))


async def test_a_completing_move_records_its_commit_and_evidence(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    await move(mcp_server, ids["task"], "In Progress")
    await move(mcp_server, ids["task"], "Complete", commit="a1b2c3d", evidence="331 passed, coverage 72%")

    assert stored(mcp_server, ids["task"]) == ("a1b2c3d", "331 passed, coverage 72%")
    shown = await details(mcp_server, ids["task"])
    assert "- **Commit**: a1b2c3d" in shown
    assert "- **Evidence**: 331 passed, coverage 72%" in shown


async def test_a_later_move_without_them_leaves_them_alone(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "In Progress", commit="a1b2c3d", evidence="21 tests passing")

    await move(mcp_server, ids["task"], "Blocked", comment="Waiting on review")

    assert stored(mcp_server, ids["task"]) == ("a1b2c3d", "21 tests passing")
    shown = await details(mcp_server, ids["task"])
    assert "- **Commit**: a1b2c3d" in shown and "- **Blocked Reason**: Waiting on review" in shown


async def test_a_new_commit_replaces_the_old_one(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "In Progress", commit="a1b2c3d")

    await move(mcp_server, ids["task"], "Complete", commit="e4f5a6b", evidence="all green")

    assert stored(mcp_server, ids["task"]) == ("e4f5a6b", "all green")


async def test_a_task_without_evidence_shows_neither_line(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    shown = await details(mcp_server, ids["task"])

    assert "**Commit**" not in shown and "**Evidence**" not in shown


def test_migration_17_adds_the_columns_to_existing_tasks(tmp_path):
    db = database_at(tmp_path / "evidence.db", version=16)
    with sqlite3.connect(db) as conn:
        conn.executescript(SEED)
        statuses = conn.execute("SELECT id, status FROM tasks ORDER BY id").fetchall()

    assert apply_all_migrations(db) == LATEST

    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, commit_ref, evidence FROM tasks ORDER BY id").fetchall() == [
            (task_id, None, None) for task_id, _ in statuses
        ]
        assert conn.execute("SELECT id, status FROM tasks ORDER BY id").fetchall() == statuses
