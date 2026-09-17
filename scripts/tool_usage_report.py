#!/usr/bin/env python3
"""Summarise tool call logs: calls per tool, errors, retries and repeats, and tools never called (roadmap R15).

Reads the server's LIFECYCLE_CALL_LOG files and the lab driver's lc-calls.jsonl, and compares the tools used with
the tools this checkout lists today.

    uv run python scripts/tool_usage_report.py LOG.jsonl [LOG.jsonl ...] [--window SECONDS]

- retry: a call to the same tool within the window after that tool returned an error
- repeat: the same tool with the same argument names called again straight after, within the window
- refused: a call the server turned away before any handler ran - its schema refused it, or no such tool exists.
  Logs written before R18 hold none of these: those calls were never logged at all, so their error counts are
  handler errors only and their call totals undercount the session (roadmap R18)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

# Kinds of failure the server refused before a handler ran, as it records them in error_kind.
REFUSED_BEFORE_HANDLER = {"validation", "unknown_tool"}


def load(path: Path) -> list[dict]:
    """Records in one log, normalised to tool, arg_names, error, kind, ms and ts (server and lab driver formats)."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        error = bool(raw.get("isError") or raw.get("in_band_error"))
        records.append(
            {
                "tool": raw["tool"],
                "arg_names": tuple(raw.get("arg_names") or sorted(raw.get("args") or {})),
                "error": error,
                # A log without error_kind predates R18, when only handlers logged and every logged error was
                # therefore a handler error.
                "kind": raw.get("error_kind") or ("handler" if error else ""),
                "ms": raw.get("ms", 0),
                "ts": datetime.fromisoformat(raw["ts"]),
            }
        )
    return records


def analyse(records: list[dict], window: float) -> dict[str, Counter]:
    stats = {
        "calls": Counter(),
        "errors": Counter(),
        "rejections": Counter(),
        "handler_errors": Counter(),
        "retries": Counter(),
        "repeats": Counter(),
        "ms": Counter(),
    }
    last_error_at: dict[str, datetime] = {}
    previous = None
    for record in records:
        tool, ts = record["tool"], record["ts"]
        stats["calls"][tool] += 1
        stats["ms"][tool] += record["ms"]
        if tool in last_error_at and (ts - last_error_at.pop(tool)).total_seconds() <= window:
            stats["retries"][tool] += 1
        if record["error"]:
            stats["errors"][tool] += 1
            stats["rejections" if record["kind"] in REFUSED_BEFORE_HANDLER else "handler_errors"][tool] += 1
            last_error_at[tool] = ts
        if (
            previous
            and previous["tool"] == tool
            and previous["arg_names"] == record["arg_names"]
            and (ts - previous["ts"]).total_seconds() <= window
        ):
            stats["repeats"][tool] += 1
        previous = record
    return stats


async def listed_tools() -> dict[str, str]:
    """Tool name -> handler for the tools this checkout lists."""
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["LIFECYCLE_DB"] = str(Path(scratch) / "report.db")
        from lifecycle_mcp.server import LifecycleMCPServer
        from lifecycle_mcp.tool_surface import measure_tools

        server = LifecycleMCPServer()
        try:
            return {size.name: size.handler for size in await measure_tools(server)}
        finally:
            server.db_manager.close()


def report(name: str, records: list[dict], tools: dict[str, str], window: float) -> set[str]:
    stats = analyse(records, window)
    used = set(stats["calls"])
    print(f"\n## {name}: {len(records)} calls, {len(used)} tools used")
    print(f"{'tool':38} {'calls':>5} {'errors':>6} {'refused':>7} {'retries':>7} {'repeats':>7} {'avg ms':>6}")
    for tool, calls in stats["calls"].most_common():
        marker = "" if tool in tools else "  (no longer listed)"
        print(
            f"{tool:38} {calls:5} {stats['errors'][tool]:6} {stats['rejections'][tool]:7} "
            f"{stats['retries'][tool]:7} {stats['repeats'][tool]:7} {stats['ms'][tool] // calls:6}{marker}"
        )
    print(
        f"errors: {stats['errors'].total()} = {stats['rejections'].total()} refused before a handler ran "
        f"+ {stats['handler_errors'].total()} handler"
    )
    if stats["rejections"].total():
        refused = ", ".join(f"{tool} {count}" for tool, count in stats["rejections"].most_common())
        print(f"refused by tool: {refused}")
    never = sorted(set(tools) - used, key=lambda tool: (tools[tool], tool))
    print(f"never called ({len(never)} of {len(tools)} listed): " + ", ".join(never))
    return used


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--window", type=float, default=120.0, help="seconds for retries and repeats (default 120)")
    options = parser.parse_args()

    tools = asyncio.run(listed_tools())
    used_anywhere: set[str] = set()
    for path in options.logs:
        used_anywhere |= report(str(path), load(path), tools, options.window)
    if len(options.logs) > 1:
        never = sorted(set(tools) - used_anywhere, key=lambda tool: (tools[tool], tool))
        print(f"\nnever called in any log ({len(never)} of {len(tools)}): " + ", ".join(never))
    return 0


if __name__ == "__main__":
    sys.exit(main())
