"""R14 acceptance: each acceptance criterion of REQ-0001-NFUNC-00 (short IDs and subtask-aware progress) through the
MCP server layer, one test per criterion in the requirement's order (TASK-0066).
"""

import sqlite3

from lifecycle_mcp.migrations import apply_all_migrations

from .test_leaf_progress import counters, subtask_of
from .test_migrations import SEED, database_at
from .test_next_tasks import move
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def test_1_get_details_accepts_the_short_forms(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    for alias, expected in (("REQ-1-FUNC", ids["requirement"]), ("TASK-1", ids["task"]), ("ADR-1", ids["adr"])):
        short = await call(mcp_server, "get_details", {"entity_id": alias})
        full = await call(mcp_server, "get_details", {"entity_id": expected})
        assert not short.isError, f"{alias}: {text_of(short)}"
        assert text_of(short) == text_of(full), alias


async def test_2_an_alias_matching_two_records_is_refused_naming_both(mcp_server):  # noqa: F811
    await populate(mcp_server)  # REQ-0001-FUNC-00
    twin = await call(mcp_server, "create_requirement", {**REQUIREMENT, "type": "TECH", "title": "Storage budget"})
    assert not twin.isError, text_of(twin)

    result = await call(mcp_server, "get_details", {"entity_id": "REQ-1"})

    assert result.isError is True
    message = text_of(result)
    assert "REQ-0001-FUNC-00" in message and "REQ-0001-TECH-00" in message


async def test_3_a_task_split_into_two_complete_subtasks_reports_two_of_two(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    first = await subtask_of(mcp_server, ids["requirement"], ids["task"], "Index writer")
    second = await subtask_of(mcp_server, ids["requirement"], ids["task"], "Index reader")

    await move(mcp_server, first, "Complete")
    await move(mcp_server, second, "Complete")

    assert counters(mcp_server, ids["requirement"]) == (2, 2)


def test_4_an_existing_database_is_corrected_by_migration_without_touching_status(tmp_path):
    db = database_at(tmp_path / "r14.db", version=15)
    with sqlite3.connect(db) as conn:
        conn.executescript(SEED)
        conn.executescript(
            """
            INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) VALUES
                ('rel-r1-parent', 'requirement', 'REQ-0001-FUNC-00', 'task', 'TASK-0001-00-00', 'implements'),
                ('rel-r1-child', 'requirement', 'REQ-0001-FUNC-00', 'task', 'TASK-0001-01-00', 'implements'),
                ('rel-child-parent', 'task', 'TASK-0001-01-00', 'task', 'TASK-0001-00-00', 'parent');
            """
        )
        before_statuses = conn.execute("SELECT id, status FROM tasks ORDER BY id").fetchall()
        assert conn.execute("SELECT task_count FROM requirements WHERE id = 'REQ-0001-FUNC-00'").fetchone() == (
            2,
        )  # the parent and its subtask both counted

    apply_all_migrations(db)

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT task_count, tasks_completed FROM requirements WHERE id = 'REQ-0001-FUNC-00'"
        ).fetchone() == (1, 1)
        assert conn.execute("SELECT id, status FROM tasks ORDER BY id").fetchall() == before_statuses
