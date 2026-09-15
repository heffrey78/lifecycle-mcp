"""Every column is reachable through the tools, and no tool declares a column that doesn't exist (R6b, TASK-0028).

Compares each table's columns in a migrated database with the create and update tool schemas the server lists. The
allowlists below are explicit on purpose: adding a column or a tool property means deciding which list it belongs to.
"""

import sqlite3

from lifecycle_mcp.handlers.architecture_handler import ARCHITECTURE_EDIT_COLUMNS
from lifecycle_mcp.handlers.requirement_handler import REQUIREMENT_EDITABLE
from lifecycle_mcp.handlers.task_handler import TASK_EDITABLE

from .test_strict_tool_inputs import listed_tools
from .test_tool_results import mcp_server  # noqa: F401 (fixture)

# table -> (create tool, update tool)
TABLES = {
    "requirements": ("create_requirement", "update_requirement"),
    "tasks": ("create_task", "update_task"),
    "architecture": ("create_architecture_decision", "update_architecture"),
}

# Columns the server maintains itself: IDs and numbering come from ID generation, status moves (and a task's
# blocked_reason) go through the update_*_status tools, counters, completed_at and superseded_by (from supersedes
# links) are kept by triggers, and GitHub fields by GitHub sync.
SYSTEM_COLUMNS = {
    "requirements": {
        "id",
        "requirement_number",
        "version",
        "status",
        "task_count",
        "tasks_completed",
        "revision",
        "created_at",
        "updated_at",
    },
    "tasks": {
        "id",
        "task_number",
        "subtask_number",
        "version",
        "status",
        "completed_at",
        "revision",
        "created_at",
        "updated_at",
        "github_issue_number",
        "github_issue_url",
        "github_etag",
        "github_last_sync",
        "blocked_reason",
    },
    "architecture": {"id", "type", "status", "revision", "created_at", "updated_at", "superseded_by"},
}

# Columns no tool can set yet, with the roadmap item that will expose each one.
PENDING_COLUMNS = {
    "requirements": {},
    "tasks": {},
    "architecture": {},
}

# Tool properties that are not columns: record IDs, links stored in relationships, and edit options.
NON_COLUMN_PROPERTIES = {
    "requirement_id",
    "task_id",
    "architecture_id",
    "requirement_ids",
    "parent_task_id",
    "reason",
    "actor",
    "if_revision",
}

# Tool properties stored under a different column name.
RENAMED_PROPERTIES = {"requirements": {}, "tasks": {}, "architecture": {"decision": "decision_outcome"}}

# Columns each update handler passes to the edit engine; the update tool schema must declare exactly these.
UPDATE_HANDLER_COLUMNS = {
    "requirements": set(REQUIREMENT_EDITABLE),
    "tasks": set(TASK_EDITABLE),
    "architecture": set(ARCHITECTURE_EDIT_COLUMNS.values()),
}


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def column_properties(table: str, properties: set[str]) -> set[str]:
    """The columns a tool's properties write, after renames and without non-column inputs."""
    return {RENAMED_PROPERTIES[table].get(name, name) for name in properties - NON_COLUMN_PROPERTIES}


async def tool_properties(server) -> dict[str, set[str]]:
    return {tool.name: set(tool.inputSchema.get("properties", {})) for tool in await listed_tools(server)}


def unreachable_columns(conn: sqlite3.Connection, properties: dict[str, set[str]]) -> dict[str, set[str]]:
    """Columns that are neither settable by the table's create or update tool nor on an allowlist, by table."""
    missing = {}
    for table, (create, update) in TABLES.items():
        settable = column_properties(table, properties[create] | properties[update])
        allowed = SYSTEM_COLUMNS[table] | set(PENDING_COLUMNS[table])
        unreachable = table_columns(conn, table) - settable - allowed
        if unreachable:
            missing[table] = unreachable
    return missing


def connect(server) -> sqlite3.Connection:
    return sqlite3.connect(server.db_manager.db_path)


async def test_every_non_system_column_is_settable_by_a_create_or_update_tool(mcp_server):  # noqa: F811
    with connect(mcp_server) as conn:
        assert unreachable_columns(conn, await tool_properties(mcp_server)) == {}


async def test_every_tool_property_is_a_column_or_an_explicit_non_column_input(mcp_server):  # noqa: F811
    properties = await tool_properties(mcp_server)
    with connect(mcp_server) as conn:
        for table, tools in TABLES.items():
            columns = table_columns(conn, table)
            for tool in tools:
                assert column_properties(table, properties[tool]) - columns == set(), tool


async def test_update_handlers_apply_exactly_the_column_properties_their_schema_declares(mcp_server):  # noqa: F811
    properties = await tool_properties(mcp_server)
    for table, (_, update) in TABLES.items():
        assert column_properties(table, properties[update]) == UPDATE_HANDLER_COLUMNS[table], update


async def test_allowlists_name_real_columns_that_no_tool_sets(mcp_server):  # noqa: F811
    properties = await tool_properties(mcp_server)
    with connect(mcp_server) as conn:
        for table, tools in TABLES.items():
            columns = table_columns(conn, table)
            allowlisted = SYSTEM_COLUMNS[table] | set(PENDING_COLUMNS[table]) | set(RENAMED_PROPERTIES[table].values())
            assert allowlisted - columns == set(), f"{table}: allowlist names a column that no longer exists"
            settable = column_properties(table, properties[tools[0]] | properties[tools[1]])
            assert (SYSTEM_COLUMNS[table] | set(PENDING_COLUMNS[table])) & settable == set(), table


async def test_a_new_column_without_a_tool_property_is_reported(mcp_server):  # noqa: F811
    properties = await tool_properties(mcp_server)
    with connect(mcp_server) as conn:
        conn.execute("ALTER TABLE tasks ADD COLUMN estimate_hours INTEGER")

        assert unreachable_columns(conn, properties) == {"tasks": {"estimate_hours"}}
