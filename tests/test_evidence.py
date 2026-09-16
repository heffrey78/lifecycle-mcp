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


# --- exported documentation (TASK-0068) -----------------------------------------------------------------------


async def export(server, tmp_path) -> dict[str, str]:
    """Export the project and return each file's text, keyed by the kind of record."""
    result = await call(
        server, "export_project_documentation", {"project_name": "evidence", "output_directory": str(tmp_path)}
    )
    assert not result.isError, text_of(result)
    return {
        kind: (tmp_path / f"evidence-{kind}.md").read_text(encoding="utf-8")
        for kind in ("requirements", "tasks", "architecture")
        if (tmp_path / f"evidence-{kind}.md").exists()
    }


async def test_the_exported_tasks_carry_their_commit_and_evidence(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "In Progress")
    await move(mcp_server, ids["task"], "Complete", commit="a1b2c3d", evidence="331 passed, coverage 72%")

    exported = await export(mcp_server, tmp_path)

    assert "- **Commit**: a1b2c3d" in exported["tasks"]
    assert "- **Evidence**: 331 passed, coverage 72%" in exported["tasks"]


async def test_the_exported_documentation_carries_comments(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    for entity_id, note in (
        (ids["requirement"], "Scope agreed with the owner"),
        (ids["task"], "Benchmarked at 26 ms p95"),
        (ids["adr"], "Revisit if FTS5 is unavailable"),
    ):
        added = await call(mcp_server, "add_comment", {"entity_id": entity_id, "comment": note, "author": "jeff"})
        assert not added.isError, text_of(added)

    exported = await export(mcp_server, tmp_path)

    assert "**Comments**:" in exported["requirements"] and "Scope agreed with the owner" in exported["requirements"]
    assert "Benchmarked at 26 ms p95" in exported["tasks"] and "jeff" in exported["tasks"]
    assert "Revisit if FTS5 is unavailable" in exported["architecture"]


async def test_records_without_evidence_or_comments_export_as_before(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)

    exported = await export(mcp_server, tmp_path)

    assert "**Comments**:" not in exported["tasks"]
    assert "**Commit**" not in exported["tasks"] and "**Evidence**" not in exported["tasks"]


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
