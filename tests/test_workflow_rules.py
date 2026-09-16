"""The rules setting and the unmet dependency rule (roadmap R8, ADR-0004, TASK-0055)."""

from lifecycle_mcp.rules import ENFORCE, OFF, RULES_ENV_FLAG, WARN, rules_mode

from .test_next_tasks import add_task, link, move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def waiting_task(server) -> tuple[str, str]:
    """A task that waits on the requirement's first task."""
    ids = await populate(server)
    api = await add_task(server, ids["requirement"], "API", "P0")
    await link(server, api, ids["task"], "depends")
    return ids["task"], api


async def start(server, task_id: str, new_status: str = "In Progress"):
    return await call(server, "update_task_status", {"task_id": task_id, "new_status": new_status})


def test_the_mode_defaults_to_warn_and_falls_back_when_it_is_not_a_mode(monkeypatch):
    monkeypatch.delenv(RULES_ENV_FLAG, raising=False)
    assert rules_mode() == WARN

    for value, expected in (("off", OFF), ("ENFORCE", ENFORCE), (" warn ", WARN), ("strict", WARN), ("", WARN)):
        monkeypatch.setenv(RULES_ENV_FLAG, value)
        assert rules_mode() == expected, value


async def test_warn_names_the_unfinished_dependencies_and_still_moves_the_task(mcp_server):  # noqa: F811
    schema, api = await waiting_task(mcp_server)

    result = await start(mcp_server, api)

    assert result.isError is False
    assert f"⚠️ Dependencies not finished: {schema} (Not Started)" in text_of(result)
    assert result.structuredContent["warnings"] == [f"Dependencies not finished: {schema} (Not Started)"]


async def test_enforce_refuses_the_same_move_and_writes_nothing(mcp_server, monkeypatch):  # noqa: F811
    schema, api = await waiting_task(mcp_server)
    monkeypatch.setenv(RULES_ENV_FLAG, "enforce")

    result = await start(mcp_server, api)

    assert result.isError is True
    assert "Refused by workflow rules (LIFECYCLE_RULES=enforce)" in text_of(result) and schema in text_of(result)
    assert f"Task {api} [Not Started]" in text_of(await call(mcp_server, "get_details", {"entity_id": api}))


async def test_off_says_nothing(mcp_server, monkeypatch):  # noqa: F811
    _, api = await waiting_task(mcp_server)
    monkeypatch.setenv(RULES_ENV_FLAG, "off")

    result = await start(mcp_server, api, "Complete")

    assert result.isError is False and "⚠️" not in text_of(result)
    assert "warnings" not in result.structuredContent


async def test_an_abandoned_dependency_says_how_to_clear_it(mcp_server):  # noqa: F811
    schema, api = await waiting_task(mcp_server)
    await move(mcp_server, schema, "Abandoned")

    result = await start(mcp_server, api)

    warning = result.structuredContent["warnings"][0]
    assert warning.startswith(f"Dependencies abandoned: {schema}")
    assert "delete_relationship" in warning and "abandon this task too" in warning


async def test_a_list_move_warns_for_the_task_it_applies_to(mcp_server):  # noqa: F811
    schema, api = await waiting_task(mcp_server)

    result = await call(mcp_server, "update_task_status", {"task_ids": [schema, api], "new_status": "In Progress"})

    assert result.structuredContent["moved"] == 2
    assert "warnings" not in result.structuredContent["results"][0]
    assert result.structuredContent["results"][1]["warnings"] == [f"Dependencies not finished: {schema} (In Progress)"]
    assert f"  ⚠️ Dependencies not finished: {schema} (In Progress)" in text_of(result)
