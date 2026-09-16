"""Tool results through the real MCP server layer: honest errors and working read tools.

Covers roadmap R4. A failure must come back with isError=true and a message an agent can act on,
and every read, query and report tool must work against a populated database.
"""

import sqlite3

import pytest
from mcp import types

from lifecycle_mcp.server import LifecycleMCPServer


@pytest.fixture
def mcp_server(temp_db, monkeypatch):
    monkeypatch.setenv("LIFECYCLE_DB", temp_db)
    server = LifecycleMCPServer()
    server.requirement_handler._testing_mode = True
    yield server
    server.db_manager.close()


async def call(server: LifecycleMCPServer, name: str, arguments: dict | None = None) -> types.CallToolResult:
    handler = server.server.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        method="tools/call", params=types.CallToolRequestParams(name=name, arguments=arguments or {})
    )
    return (await handler(request)).root


def text_of(result: types.CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, types.TextContent))


REQUIREMENT = {
    "type": "FUNC",
    "title": "Searchable notes",
    "priority": "P1",
    "current_state": "No search",
    "desired_state": "Ranked full-text search",
    "acceptance_criteria": ["Returns matching notes"],
}


async def populate(server: LifecycleMCPServer) -> dict[str, str]:
    await call(server, "create_requirement", REQUIREMENT)
    req_id = "REQ-0001-FUNC-00"
    for status in ("Under Review", "Approved"):
        assert not (
            await call(server, "update_requirement_status", {"requirement_id": req_id, "new_status": status})
        ).isError
    task = await call(server, "create_task", {"requirement_ids": [req_id], "title": "Build index", "priority": "P1"})
    assert not task.isError, text_of(task)
    adr = await call(
        server,
        "create_architecture_decision",
        {"requirement_ids": [req_id], "title": "Use FTS5", "context": "Need search", "decision": "SQLite FTS5"},
    )
    assert not adr.isError, text_of(adr)
    return {"requirement": req_id, "task": "TASK-0001-00-00", "adr": "ADR-0001"}


# --- honest errors -------------------------------------------------------------------------------


async def test_success_is_not_flagged_as_error(mcp_server):
    result = await call(mcp_server, "create_requirement", REQUIREMENT)
    assert result.isError is False
    assert text_of(result).startswith("[SUCCESS]")


async def test_not_found_is_flagged_as_error(mcp_server):
    result = await call(mcp_server, "get_details", {"entity_id": "REQ-9999-FUNC-00"})
    assert result.isError is True
    assert "not found" in text_of(result)


async def test_gate_refusal_is_an_error_with_its_explanation(mcp_server):
    await call(mcp_server, "create_requirement", REQUIREMENT)
    result = await call(
        mcp_server, "create_task", {"requirement_ids": ["REQ-0001-FUNC-00"], "title": "Too early", "priority": "P2"}
    )
    assert result.isError is True
    assert "must be approved first" in text_of(result)


async def test_unexpected_exception_message_reaches_the_agent(mcp_server, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error: simulated")

    monkeypatch.setattr(mcp_server.requirement_handler.db, "get_records", broken)
    result = await call(mcp_server, "get_details", {"entity_id": "REQ-0001-FUNC-00"})
    assert result.isError is True
    assert "disk I/O error: simulated" in text_of(result)


async def test_unknown_tool_is_an_error(mcp_server):
    result = await call(mcp_server, "no_such_tool", {})
    assert result.isError is True


# --- every read tool works on real rows ----------------------------------------------------------


async def test_every_read_query_and_report_tool_succeeds_on_populated_db(mcp_server, tmp_path):
    ids = await populate(mcp_server)
    calls = [
        ("query_requirements", {}),
        ("get_details", {"entity_id": ids["requirement"]}),
        ("trace_requirement", {"requirement_id": ids["requirement"]}),
        ("query_tasks", {}),
        ("query_tasks", {"requirement_id": ids["requirement"]}),
        ("get_details", {"entity_id": ids["task"]}),
        ("query_architecture_decisions", {}),
        ("query_architecture_decisions", {"requirement_id": ids["requirement"]}),
        ("get_details", {"entity_id": ids["adr"]}),
        ("query_relationships", {"entity_id": ids["task"]}),
        ("query_relationships", {"entity_id": ids["requirement"], "direction": "outgoing"}),
        ("query_relationships", {"entity_types": ["requirement", "task"]}),
        ("get_project_status", {"include_blocked": True}),
        ("export_project_documentation", {"project_name": "smoke", "output_directory": str(tmp_path / "docs")}),
    ]
    calls += [
        ("create_architectural_diagrams", {"diagram_type": kind, "output_path": str(tmp_path / "diagrams")})
        for kind in ("requirements", "tasks", "architecture", "full_project", "dependencies")
    ]

    failures = []
    for name, arguments in calls:
        result = await call(mcp_server, name, arguments)
        if result.isError:
            failures.append(f"{name}({arguments}): {text_of(result)[:200]}")
    assert failures == []


async def test_architecture_details_include_the_decision(mcp_server):
    ids = await populate(mcp_server)
    result = await call(mcp_server, "get_details", {"entity_id": ids["adr"]})
    assert result.isError is False
    assert "SQLite FTS5" in text_of(result) and ids["requirement"] in text_of(result)
