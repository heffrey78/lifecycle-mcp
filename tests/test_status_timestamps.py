"""Status tools store a real updated_at timestamp, not the text CURRENT_TIMESTAMP (F-42, roadmap R4, TASK-0033)."""

import sqlite3
from datetime import datetime

from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


def stored_updated_at(server, table: str, record_id: str) -> str:
    with sqlite3.connect(server.db_manager.db_path) as conn:
        return conn.execute(f"SELECT updated_at FROM {table} WHERE id = ?", [record_id]).fetchone()[0]


async def test_every_status_tool_stores_a_parseable_updated_at(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    changes = [
        (
            "update_requirement_status",
            {"requirement_id": ids["requirement"], "new_status": "Ready"},
            "requirements",
            ids["requirement"],
        ),
        (
            "update_task_status",
            {"task_id": ids["task"], "new_status": "In Progress", "assignee": "agent"},
            "tasks",
            ids["task"],
        ),
        (
            "update_architecture_status",
            {"architecture_id": ids["adr"], "new_status": "Accepted"},
            "architecture",
            ids["adr"],
        ),
    ]

    for tool, arguments, table, record_id in changes:
        result = await call(mcp_server, tool, arguments)
        assert not result.isError, text_of(result)
        value = stored_updated_at(mcp_server, table, record_id)
        assert datetime.strptime(value, "%Y-%m-%d %H:%M:%S"), f"{tool} stored {value!r}"

    task = text_of(await call(mcp_server, "get_details", {"entity_id": ids["task"]}))
    assert "**Status**: In Progress" in task and "**Assignee**: agent" in task
    decision = text_of(await call(mcp_server, "get_details", {"entity_id": ids["adr"]}))
    assert "**Status**: Accepted" in decision and "**Updated**: CURRENT_TIMESTAMP" not in decision
