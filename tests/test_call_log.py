"""Opt-in tool call log for usage evidence (roadmap R15, TASK-0030)."""

import json

from lifecycle_mcp.server import CALL_LOG_ENV

from .test_tool_results import REQUIREMENT, call, mcp_server  # noqa: F401 (mcp_server is a fixture)


async def test_each_call_is_logged_with_argument_names_and_outcome_but_no_values(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv(CALL_LOG_ENV, str(log))

    await call(mcp_server, "create_requirement", REQUIREMENT)
    await call(mcp_server, "get_details", {"entity_id": "REQ-9999-FUNC-00"})

    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [(r["tool"], r["isError"]) for r in records] == [
        ("create_requirement", False),
        ("get_details", True),
    ]
    assert records[0]["arg_names"] == sorted(REQUIREMENT)
    assert all(r["ms"] >= 0 and r["response_chars"] > 0 and r["ts"].endswith("+00:00") for r in records)
    assert "Searchable notes" not in log.read_text(encoding="utf-8")


async def test_nothing_is_logged_when_the_log_is_not_configured(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.delenv(CALL_LOG_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    result = await call(mcp_server, "create_requirement", REQUIREMENT)

    assert result.isError is False
    assert list(tmp_path.iterdir()) == []


async def test_an_unwritable_log_does_not_fail_the_call(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv(CALL_LOG_ENV, str(tmp_path / "missing-directory" / "calls.jsonl"))

    result = await call(mcp_server, "create_requirement", REQUIREMENT)

    assert result.isError is False
