"""R18 acceptance: each acceptance criterion of REQ-0006-TECH-00 (the call log sees every call, including the
refused ones) through the MCP server layer, one test per criterion in the requirement's order.

The failure this closes (F-53): schema validation ran before any handler, and only handlers logged, so a call the
schema refused left no trace in LIFECYCLE_CALL_LOG - the class of error the log was most wanted for.
"""

import importlib.util
import json
from pathlib import Path

from lifecycle_mcp.server import CALL_LOG_ENV

from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

ROOT = Path(__file__).resolve().parent.parent


def records(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def usage_report():
    """scripts/tool_usage_report.py, which is a script rather than a package module."""
    spec = importlib.util.spec_from_file_location("tool_usage_report", ROOT / "scripts" / "tool_usage_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_1_a_wrong_type_is_logged_with_the_parameter_and_no_value(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv(CALL_LOG_ENV, str(log))

    result = await call(
        mcp_server, "update_requirement_status", {"requirement_id": ["REQ-0001-FUNC-00"], "new_status": "Approved"}
    )
    assert result.isError is True

    (entry,) = records(log)
    assert entry["tool"] == "update_requirement_status"
    assert entry["isError"] is True
    assert entry["error_kind"] == "validation"
    assert entry["rejected"] == {"rule": "type", "param": "requirement_id"}
    assert entry["arg_names"] == ["new_status", "requirement_id"]
    # The rejection reason names the rule and the parameter; the value that was passed stays out of the log.
    assert "REQ-0001-FUNC-00" not in log.read_text(encoding="utf-8")


async def test_2_a_call_naming_a_tool_that_does_not_exist_is_logged(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv(CALL_LOG_ENV, str(log))

    result = await call(mcp_server, "no_such_tool", {})
    assert result.isError is True

    (entry,) = records(log)
    assert entry["tool"] == "no_such_tool"
    assert entry["isError"] is True
    assert entry["error_kind"] == "unknown_tool"


async def test_3_the_report_separates_refusals_and_the_totals_add_up(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv(CALL_LOG_ENV, str(log))

    await call(mcp_server, "create_requirement", REQUIREMENT)  # succeeds
    await call(mcp_server, "get_details", {"entity_id": "REQ-9999-FUNC-00"})  # handler error
    await call(mcp_server, "update_task_status", {"task_id": ["TASK-0001-00-00"], "new_status": "Complete"})  # refused
    await call(mcp_server, "no_such_tool", {})  # refused

    module = usage_report()
    stats = module.analyse(module.load(log), 120.0)

    assert stats["rejections"]["update_task_status"] == 1
    assert stats["rejections"]["no_such_tool"] == 1
    assert stats["handler_errors"]["get_details"] == 1
    assert stats["rejections"]["get_details"] == 0
    assert stats["calls"].total() == 4
    assert stats["errors"].total() == stats["rejections"].total() + stats["handler_errors"].total() == 3


def test_4_the_usage_evidence_records_that_earlier_figures_undercount_refused_calls():
    evidence = (ROOT / "docs" / "tool-surface" / "usage-evidence.md").read_text(encoding="utf-8")

    assert "undercount" in evidence.lower()
    assert "refused" in evidence.lower()


async def test_5_every_call_the_server_receives_appears_in_the_log(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    """The requirement's validation metric: a session's server-side count matches the calls actually made."""
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv(CALL_LOG_ENV, str(log))

    made = [
        ("create_requirement", REQUIREMENT),
        ("query_requirements", {}),
        ("get_details", {"entity_id": "REQ-9999-FUNC-00"}),
        ("create_requirement", {**REQUIREMENT, "title": ["a list"]}),
        ("create_requirement", {**REQUIREMENT, "not_a_real_field": 1}),
        ("no_such_tool", {}),
    ]
    for name, arguments in made:
        await call(mcp_server, name, arguments)

    logged = records(log)
    assert [entry["tool"] for entry in logged] == [name for name, _ in made]
    assert sum(entry["isError"] for entry in logged) == 4
