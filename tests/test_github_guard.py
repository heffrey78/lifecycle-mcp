"""GitHub integration is opt-in, and tests can never reach real GitHub."""

import asyncio
import subprocess
import sys

import pytest

from lifecycle_mcp.github_utils import GITHUB_ENV_FLAG, GitHubUtils


def _approved_requirement(db_manager, req_id="REQ-0001-FUNC-00"):
    db_manager.insert_record(
        "requirements",
        {
            "id": req_id,
            "requirement_number": 1,
            "type": "FUNC",
            "title": "GitHub flag requirement",
            "priority": "P2",
            "current_state": "current",
            "desired_state": "desired",
            "author": "tests",
            "status": "Approved",
        },
    )
    return req_id


# --- the opt-in flag -----------------------------------------------------------------------------


def test_github_is_disabled_by_default():
    assert GitHubUtils.is_github_enabled() is False
    assert GitHubUtils.is_github_available() is False
    assert f"{GITHUB_ENV_FLAG}=on" in GitHubUtils.unavailable_reason()


@pytest.mark.parametrize("value", ["on", "1", "true", "YES", " On "])
def test_flag_values_that_enable(monkeypatch, value):
    monkeypatch.setenv(GITHUB_ENV_FLAG, value)
    assert GitHubUtils.is_github_enabled() is True


@pytest.mark.parametrize("value", ["", "off", "0", "no", "false", "enabled"])
def test_flag_values_that_do_not_enable(monkeypatch, value):
    monkeypatch.setenv(GITHUB_ENV_FLAG, value)
    assert GitHubUtils.is_github_enabled() is False


async def test_health_check_reports_disabled_without_running_gh():
    health = await GitHubUtils.check_github_health()
    assert health["enabled"] is False
    assert health["github_cli_available"] is False


# --- the test guard ------------------------------------------------------------------------------


def test_guard_blocks_gh_even_when_flag_is_on(monkeypatch):
    monkeypatch.setenv(GITHUB_ENV_FLAG, "on")
    with pytest.raises(pytest.fail.Exception, match="blocked in tests"):
        GitHubUtils.is_github_available()


async def test_guard_blocks_async_gh_subprocesses():
    with pytest.raises(pytest.fail.Exception, match="blocked in tests"):
        await asyncio.create_subprocess_exec("gh", "issue", "list")


@pytest.mark.parametrize("command", [["git", "status"], "gh issue list", ["/usr/bin/gh", "--version"]])
def test_guard_blocks_every_spelling(command):
    with pytest.raises(pytest.fail.Exception):
        subprocess.run(command, shell=isinstance(command, str), capture_output=True)


def test_guard_allows_other_programs():
    result = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ok"


# --- create_task behaviour -----------------------------------------------------------------------


async def test_create_task_makes_no_github_calls_when_disabled(task_handler, db_manager, monkeypatch):
    calls = []

    async def fake_create_issue(**kwargs):
        calls.append(kwargs)
        return "https://github.com/example/repo/issues/1"

    monkeypatch.setattr(GitHubUtils, "create_github_issue", staticmethod(fake_create_issue))
    req_id = _approved_requirement(db_manager)

    result = await task_handler.handle_tool_call(
        "create_task", {"requirement_ids": [req_id], "title": "Local only", "priority": "P2"}
    )

    assert calls == []
    assert "GitHub sync disabled" in result[0].text
    [task] = db_manager.get_records("tasks", "github_issue_number", "title = ?", ["Local only"])
    assert task["github_issue_number"] is None


async def test_create_task_records_the_issue_when_enabled(task_handler, db_manager, monkeypatch):
    monkeypatch.setenv(GITHUB_ENV_FLAG, "on")
    created = []

    async def fake_create_issue(**kwargs):
        created.append(kwargs)
        return "https://github.com/example/repo/issues/42"

    async def fake_get_issue(number):
        return {"number": int(number), "state": "OPEN", "etag": "etag-42"}

    monkeypatch.setattr(GitHubUtils, "is_github_available", staticmethod(lambda: True))
    monkeypatch.setattr(GitHubUtils, "create_github_issue", staticmethod(fake_create_issue))
    monkeypatch.setattr(GitHubUtils, "get_github_issue", staticmethod(fake_get_issue))
    req_id = _approved_requirement(db_manager)

    result = await task_handler.handle_tool_call(
        "create_task", {"requirement_ids": [req_id], "title": "Synced", "priority": "P1", "effort": "S"}
    )

    assert len(created) == 1 and created[0]["title"].endswith("Synced")
    assert "github.com/example/repo/issues/42" in result[0].text
    [task] = db_manager.get_records("tasks", "github_issue_number, github_etag", "title = ?", ["Synced"])
    assert task["github_issue_number"] == "42" and task["github_etag"] == "etag-42"
