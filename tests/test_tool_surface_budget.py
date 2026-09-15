"""The tool surface stays within its recorded budget (roadmap R15, TASK-0029).

Growing the number of tools or the size of their definitions is allowed, but only on purpose: raise the numbers in
tests/tool_surface_budget.json in the same change. scripts/tool_surface_report.py shows where the size is.
"""

import json
from pathlib import Path

from lifecycle_mcp.tool_surface import ToolSize, measure_tools, over_budget, totals

from .test_tool_results import mcp_server  # noqa: F401 (fixture)

BUDGET_FILE = Path(__file__).with_name("tool_surface_budget.json")


async def test_tool_surface_stays_within_budget(mcp_server):  # noqa: F811
    budget = json.loads(BUDGET_FILE.read_text(encoding="utf-8"))

    problems = over_budget(await measure_tools(mcp_server), budget)

    assert problems == [], (
        f"Tool surface over budget. If the growth is intended, raise the numbers in {BUDGET_FILE.name} in this "
        "change (scripts/tool_surface_report.py shows where the size is):\n" + "\n".join(problems)
    )


async def test_every_handler_has_a_budget_entry(mcp_server):  # noqa: F811
    budget = json.loads(BUDGET_FILE.read_text(encoding="utf-8"))

    measured = set(totals(await measure_tools(mcp_server))) - {"total"}

    assert measured == set(budget["handlers"])


def test_an_exceeded_budget_names_the_handler_its_size_and_its_budget():
    sizes = [ToolSize("create_note", "Note", 700), ToolSize("delete_note", "Note", 400), ToolSize("sync", "Sync", 90)]
    budget = {
        "total": {"tools": 3, "chars": 1000},
        "handlers": {"Note": {"tools": 2, "chars": 1000}},
    }

    assert over_budget(sizes, budget) == [
        "Note: 1100 chars, budget 1000",
        "Sync: 1 tools, 90 chars, and no budget recorded",
        "total: 1190 chars, budget 1000",
    ]
