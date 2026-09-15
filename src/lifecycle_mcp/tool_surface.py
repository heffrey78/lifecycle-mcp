"""Measure the tool surface an MCP client sees: how many tools there are and how large their definitions are.

Every definition in tools/list is sent to the client and costs context on every request (roadmap R15). The budget
test and scripts/tool_surface_report.py both measure through here, so they always agree.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp import types

if TYPE_CHECKING:
    from .server import LifecycleMCPServer


@dataclass(frozen=True)
class ToolSize:
    name: str
    handler: str  # handler class name without the "Handler" suffix, e.g. "Requirement"
    chars: int  # length of the definition as tools/list serialises it


async def measure_tools(server: LifecycleMCPServer) -> list[ToolSize]:
    """Size of each listed tool definition, attributed to the handler that serves it."""
    list_tools = server.server.request_handlers[types.ListToolsRequest]
    tools = (await list_tools(types.ListToolsRequest(method="tools/list"))).root.tools
    return [
        ToolSize(
            name=tool.name,
            handler=type(server.handlers[tool.name]).__name__.removesuffix("Handler"),
            chars=len(tool.model_dump_json(by_alias=True, exclude_none=True)),
        )
        for tool in tools
    ]


def totals(sizes: Iterable[ToolSize]) -> dict[str, dict[str, int]]:
    """Tool count and definition size per handler, plus a "total" entry."""
    result: dict[str, dict[str, int]] = {"total": {"tools": 0, "chars": 0}}
    for size in sizes:
        for key in (size.handler, "total"):
            entry = result.setdefault(key, {"tools": 0, "chars": 0})
            entry["tools"] += 1
            entry["chars"] += size.chars
    return result


def over_budget(sizes: Iterable[ToolSize], budget: dict[str, Any]) -> list[str]:
    """One line per handler (or the total) whose tool count or definition size exceeds its budget.

    budget has the shape {"total": {"tools": n, "chars": n}, "handlers": {name: {"tools": n, "chars": n}}}. A handler
    without a budget is reported too, so a new handler cannot slip past the check.
    """
    problems = []
    for name, measured in sorted(totals(sizes).items()):
        allowed = budget["total"] if name == "total" else budget["handlers"].get(name)
        if allowed is None:
            problems.append(f"{name}: {measured['tools']} tools, {measured['chars']} chars, and no budget recorded")
            continue
        for key, unit in (("tools", "tools"), ("chars", "chars")):
            if measured[key] > allowed[key]:
                problems.append(f"{name}: {measured[key]} {unit}, budget {allowed[key]}")
    return problems
