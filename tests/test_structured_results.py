"""Tool results carry structuredContent next to their text, without an outputSchema (roadmap R10)."""

from .test_strict_tool_inputs import listed_tools
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def test_create_requirement_is_one_status_line_plus_structured_data(mcp_server):  # noqa: F811
    result = await call(mcp_server, "create_requirement", REQUIREMENT)

    assert result.isError is False
    assert text_of(result) == "[SUCCESS] Requirement REQ-0001-FUNC-00 created"
    assert result.structuredContent == {
        "id": "REQ-0001-FUNC-00",
        "type": "FUNC",
        "title": "Searchable notes",
        "priority": "P1",
        "status": "Draft",
    }


async def test_results_without_structured_data_leave_structured_content_empty(mcp_server):  # noqa: F811
    await call(mcp_server, "create_requirement", REQUIREMENT)

    result = await call(mcp_server, "get_entity_history", {"entity_id": "REQ-0001-FUNC-00"})

    assert result.isError is False and result.structuredContent is None


async def test_no_tool_declares_an_output_schema(mcp_server):  # noqa: F811
    assert [tool.name for tool in await listed_tools(mcp_server) if tool.outputSchema is not None] == []


# --- query tools (TASK-0041: they replace the *_json tools) -------------------------------------------


async def test_query_tools_return_the_full_records_as_structured_data(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    edit = {"requirement_id": ids["requirement"], "business_value": "Faster lookup", "reason": "Value stated"}
    assert not (await call(mcp_server, "update_requirement", edit)).isError

    requirements = await call(mcp_server, "query_requirements", {})
    assert "Found 1 requirement(s)" in text_of(requirements)
    assert requirements.structuredContent["count"] == 1
    requirement = requirements.structuredContent["requirements"][0]
    assert requirement["id"] == ids["requirement"] and requirement["status"] == "Approved"
    assert requirement["acceptance_criteria"] == ["Returns matching notes"]
    assert requirement["business_value"] == "Faster lookup"  # plain text stays text

    tasks = await call(mcp_server, "query_tasks", {"requirement_id": ids["requirement"]})
    assert tasks.structuredContent["count"] == 1
    task = tasks.structuredContent["tasks"][0]
    assert task["id"] == ids["task"] and task["acceptance_criteria"] == []

    decisions = await call(mcp_server, "query_architecture_decisions", {"requirement_id": ids["requirement"]})
    assert decisions.structuredContent["count"] == 1
    decision = decisions.structuredContent["architecture_decisions"][0]
    assert decision["id"] == ids["adr"] and decision["decision_outcome"] == "SQLite FTS5"
    assert decision["authors"] == ["MCP User"]


async def test_an_empty_query_returns_an_empty_structured_list(mcp_server):  # noqa: F811
    result = await call(mcp_server, "query_tasks", {"status": "Blocked"})

    assert "No tasks found" in text_of(result)
    assert result.structuredContent == {"tasks": [], "count": 0}


async def test_project_status_returns_the_metrics_as_structured_data(mcp_server):  # noqa: F811
    await populate(mcp_server)

    result = await call(mcp_server, "get_project_status", {})

    assert "# Project Status Dashboard" in text_of(result)
    metrics = result.structuredContent
    assert metrics["requirements"]["by_status"] == {"Approved": 1} and metrics["requirements"]["total"] == 1
    assert metrics["tasks"]["by_status"] == {"Not Started": 1} and metrics["tasks"]["total"] == 1
    assert metrics["architecture"] == {"by_status": {"Proposed": 1}, "total": 1}
    assert metrics["summary"]["completed_tasks"] == 0

    removed = await call(mcp_server, "get_project_metrics", {})
    assert removed.isError and "Unknown tool" in text_of(removed)


async def test_the_json_twins_are_gone(mcp_server):  # noqa: F811
    for name in ("query_requirements_json", "query_tasks_json", "query_architecture_decisions_json"):
        result = await call(mcp_server, name, {})
        assert result.isError and "Unknown tool" in text_of(result), name


# --- create, update and status tools (TASK-0043) --------------------------------------------------------


async def structured(server, name: str, arguments: dict) -> dict:
    result = await call(server, name, arguments)
    assert result.isError is False, text_of(result)
    return result.structuredContent


async def test_create_tools_return_the_new_records_id_and_status(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    task = {"requirement_ids": [ids["requirement"]], "title": "Rank results", "priority": "P1"}
    decision = {
        "requirement_ids": [ids["requirement"]],
        "title": "Use BM25",
        "context": "Ranking",
        "decision": "bm25()",
    }

    assert await structured(mcp_server, "create_task", {**task, "parent_task_id": ids["task"]}) == {
        "id": "TASK-0001-01-00",
        "status": "Not Started",
        "requirement_ids": [ids["requirement"]],
        "parent_task_id": ids["task"],
        "github_issue_url": None,
    }
    assert await structured(mcp_server, "create_architecture_decision", decision) == {
        "id": "ADR-0002",
        "status": "Proposed",
        "requirement_ids": [ids["requirement"]],
    }


async def test_update_tools_return_the_changed_fields_and_new_revision(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    requirement = {"requirement_id": ids["requirement"], "business_value": "Faster lookup", "reason": "Value stated"}
    assert await structured(mcp_server, "update_requirement", requirement) == {
        "id": ids["requirement"],
        "changed": ["business_value"],
        "revision": 1,
        "changed_since_review": True,
    }
    assert await structured(mcp_server, "update_task", {"task_id": ids["task"], "title": "Build FTS index"}) == {
        "id": ids["task"],
        "changed": ["title"],
        "revision": 1,
    }
    decision = {"architecture_id": ids["adr"], "title": "Use FTS5 with trigrams"}
    assert await structured(mcp_server, "update_architecture", decision) == {
        "id": ids["adr"],
        "changed": ["title"],
        "revision": 1,
    }


async def test_status_tools_return_the_old_and_new_status(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    changes = [
        (
            "update_requirement_status",
            {"requirement_id": ids["requirement"], "new_status": "Ready"},
            ids["requirement"],
            "Approved",
            "Ready",
        ),
        (
            "update_task_status",
            {"task_id": ids["task"], "new_status": "In Progress"},
            ids["task"],
            "Not Started",
            "In Progress",
        ),
        (
            "update_architecture_status",
            {"architecture_id": ids["adr"], "new_status": "Accepted"},
            ids["adr"],
            "Proposed",
            "Accepted",
        ),
    ]
    for tool, arguments, record_id, before, after in changes:
        assert await structured(mcp_server, tool, arguments) == {
            "id": record_id,
            "from_status": before,
            "to_status": after,
        }, tool
