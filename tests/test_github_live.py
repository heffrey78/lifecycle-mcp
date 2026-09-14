"""Opt-in end-to-end test against a real GitHub repository.

It creates a real issue in the repository of the current working directory, so it is skipped
unless all of these hold:
  * LIFECYCLE_GITHUB_LIVE=1
  * LIFECYCLE_GITHUB_LIVE_REPO=<owner/name> names a sandbox repository
  * the current checkout's origin is that repository

Every issue the test creates is closed on teardown by ``github_issue_cleanup``.

    LIFECYCLE_GITHUB_LIVE=1 LIFECYCLE_GITHUB_LIVE_REPO=me/lifecycle-sandbox \
        uv run pytest tests/test_github_live.py -m github_live
"""

import os
import subprocess

import pytest

from lifecycle_mcp.github_utils import GitHubUtils


def _origin_is_sandbox() -> bool:
    repo = os.environ.get("LIFECYCLE_GITHUB_LIVE_REPO", "")
    if not repo:
        return False
    result = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=False)
    url = result.stdout.strip().removesuffix(".git")
    return result.returncode == 0 and (url.endswith(f"/{repo}") or url.endswith(f":{repo}"))


pytestmark = [
    pytest.mark.github_live,
    pytest.mark.skipif(
        os.environ.get("LIFECYCLE_GITHUB_LIVE") != "1" or not _origin_is_sandbox(),
        reason=(
            "live GitHub test: set LIFECYCLE_GITHUB_LIVE=1 and LIFECYCLE_GITHUB_LIVE_REPO "
            "to this checkout's sandbox origin"
        ),
    ),
]


async def test_task_status_round_trips_through_a_real_issue(
    task_handler, db_manager, github_issue_cleanup, monkeypatch
):
    monkeypatch.setenv("LIFECYCLE_GITHUB", "on")
    db_manager.insert_record(
        "requirements",
        {
            "id": "REQ-0001-FUNC-00",
            "requirement_number": 1,
            "type": "FUNC",
            "title": "Live GitHub requirement",
            "priority": "P3",
            "current_state": "n/a",
            "desired_state": "n/a",
            "author": "live test",
            "status": "Approved",
        },
    )

    await task_handler.handle_tool_call(
        "create_task", {"requirement_ids": ["REQ-0001-FUNC-00"], "title": "Live GitHub round trip", "priority": "P3"}
    )
    [task] = db_manager.get_records("tasks", "id, github_issue_number", "title = ?", ["Live GitHub round trip"])
    assert task["github_issue_number"], "create_task did not create an issue"
    github_issue_cleanup.append(task["github_issue_number"])

    await task_handler.handle_tool_call("update_task_status", {"task_id": task["id"], "new_status": "Complete"})
    issue = await GitHubUtils.get_github_issue(str(task["github_issue_number"]))
    assert issue and issue["state"].lower() == "closed"
