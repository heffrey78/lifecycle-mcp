#!/usr/bin/env python3
"""Report the tool surface an MCP client sees: tool count and definition size per handler and per tool.

Starts the server from this checkout against a throwaway database, measures tools/list the same way the budget
test does, and compares the result with tests/tool_surface_budget.json (roadmap R15).

    uv run python scripts/tool_surface_report.py
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGET_FILE = ROOT / "tests" / "tool_surface_budget.json"


async def main() -> int:
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["LIFECYCLE_DB"] = str(Path(scratch) / "report.db")
        from lifecycle_mcp.server import LifecycleMCPServer
        from lifecycle_mcp.tool_surface import measure_tools, over_budget, totals

        server = LifecycleMCPServer()
        try:
            sizes = await measure_tools(server)
        finally:
            server.db_manager.close()

    budget = json.loads(BUDGET_FILE.read_text(encoding="utf-8")) if BUDGET_FILE.exists() else None
    summary = totals(sizes)
    total = summary.pop("total")

    print(f"{'handler':14} {'tools':>5} {'chars':>7} {'~tokens':>8}   budget (tools / chars)")
    for handler, measured in sorted(summary.items(), key=lambda item: -item[1]["chars"]):
        allowed = budget["handlers"].get(handler) if budget else None
        limit = f"{allowed['tools']} / {allowed['chars']}" if allowed else "none"
        print(f"{handler:14} {measured['tools']:5} {measured['chars']:7} {measured['chars'] // 4:8}   {limit}")
    limit = f"{budget['total']['tools']} / {budget['total']['chars']}" if budget else "none"
    print(f"{'total':14} {total['tools']:5} {total['chars']:7} {total['chars'] // 4:8}   {limit}")

    print(f"\n{'tool':38} {'handler':14} {'chars':>6}")
    for size in sorted(sizes, key=lambda item: -item.chars):
        print(f"{size.name:38} {size.handler:14} {size.chars:6}")

    if budget is None:
        print(f"\nNo budget file at {BUDGET_FILE}")
        return 0
    problems = over_budget(sizes, budget)
    print("\nOver budget:\n" + "\n".join(f"  {line}" for line in problems) if problems else "\nWithin budget")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
