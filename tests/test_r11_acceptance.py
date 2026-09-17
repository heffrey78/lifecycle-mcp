"""R11 acceptance: each acceptance criterion of REQ-0006-FUNC-00 (fields that get filled, requirements that stay
fresh) through the MCP server layer, one test per criterion in the requirement's order (TASK-0074).
"""

import time
from pathlib import Path

from lifecycle_mcp.prompts import CAPTURE_REQUIREMENT
from lifecycle_mcp.rules import RULES_ENV_FLAG

from .test_prompts import get_prompt, list_prompts
from .test_staleness import dashboard, details, new_requirement
from .test_thin_records import NFUNC
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def test_1_an_nfunc_requirement_without_validation_metrics_is_named_and_can_be_enforced(
    mcp_server,  # noqa: F811
    monkeypatch,
):
    warned = await call(mcp_server, "create_requirement", NFUNC)
    assert warned.isError is False
    assert "validation_metrics" in warned.structuredContent["warnings"][0]

    monkeypatch.setenv(RULES_ENV_FLAG, "enforce")
    refused = await call(mcp_server, "create_requirement", {**NFUNC, "title": "Search stays fast too"})
    assert refused.isError is True and "validation_metrics" in text_of(refused)


async def test_2_a_high_priority_task_without_a_test_plan_is_named(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    result = await call(
        mcp_server, "create_task", {"requirement_ids": [ids["requirement"]], "title": "Rank", "priority": "P0"}
    )

    assert result.isError is False and "test_plan" in result.structuredContent["warnings"][0]


async def test_3_off_warns_about_neither(mcp_server, monkeypatch):  # noqa: F811
    monkeypatch.setenv(RULES_ENV_FLAG, "off")
    ids = await populate(mcp_server)

    requirement = await call(mcp_server, "create_requirement", NFUNC)
    task = await call(
        mcp_server, "create_task", {"requirement_ids": [ids["requirement"]], "title": "Rank", "priority": "P0"}
    )

    assert "warnings" not in requirement.structuredContent
    assert "warnings" not in task.structuredContent


async def test_4_the_capture_prompt_is_offered_and_its_example_fills_the_curated_fields(mcp_server):  # noqa: F811
    assert CAPTURE_REQUIREMENT in [prompt.name for prompt in await list_prompts(mcp_server)]

    guide = (await get_prompt(mcp_server, CAPTURE_REQUIREMENT)).messages[0].content.text
    assert "validation_metrics" in guide and "create_requirement(" in guide

    # The worked example the prompt shows, sent as the client's model would send it.
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "NFUNC",
            "title": "Search stays fast as notes grow",
            "priority": "P1",
            "current_state": "Search runs unindexed; at 10k notes a query takes about 900 ms.",
            "desired_state": "Search stays quick as the collection grows.",
            "acceptance_criteria": ["A search over 10k notes returns in under 50 ms at p95"],
            "validation_metrics": ["Search p95 under 50 ms at 10k notes"],
            "out_of_scope": ["Ranking quality"],
        },
    )

    assert not result.isError and "warnings" not in result.structuredContent
    shown = await details(mcp_server, result.structuredContent["id"])
    assert "Search p95 under 50 ms at 10k notes" in shown and "Ranking quality" in shown


async def test_5_a_requirement_changed_after_its_last_check_shows_as_stale(mcp_server):  # noqa: F811
    requirement = await new_requirement(mcp_server)
    await call(mcp_server, "add_comment", {"entity_id": requirement, "comment": "Checked against the code"})
    time.sleep(1.1)  # comment times are second-resolution

    edited = await call(
        mcp_server, "update_requirement", {"requirement_id": requirement, "current_state": "Now it is indexed"}
    )
    assert not edited.isError, text_of(edited)

    # R17 changed the wording of both signals; the criterion they answer is unchanged.
    assert "**⚠️ Not Verified Since It Changed**" in await details(mcp_server, requirement)
    assert "Needs Verification (1)" in await dashboard(mcp_server)


def test_6_no_handler_references_mcp_client_or_sampling():
    source = Path("src/lifecycle_mcp")
    offenders = [
        f"{path.relative_to(source)}:{number}"
        for path in source.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if "mcp_client" in line or "sampling" in line.lower()
    ]

    assert offenders == []
    assert not (source / "llm_decomposition_prompts.py").exists()
