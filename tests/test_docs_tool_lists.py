"""README and CLAUDE.md list exactly the tools the server lists (roadmap R16, TASK-0039).

The docs' tool lists have gone stale before (CLAUDE.md said 22 tools while the server listed 32). This compares them
with the live tools/list, with GitHub integration off and on, so a change to the tool surface must update the docs.
"""

import re
from pathlib import Path

from lifecycle_mcp.github_utils import GITHUB_ENV_FLAG

from .test_strict_tool_inputs import listed_tools
from .test_tool_results import mcp_server  # noqa: F401 (fixture)

ROOT = Path(__file__).resolve().parent.parent

# doc -> (heading that starts its tool list, heading after it, pattern for its "N tools (M with GitHub on)" statements)
DOCS = {
    "README.md": ("### Tool List", "### Editing, Deleting and History", r"exposes (\d+) MCP tools \((\d+) with"),
    "CLAUDE.md": (
        "### MCP Tools Available",
        "### Database Environment",
        r"(\d+) tools \((\d+) with `LIFECYCLE_GITHUB=on`\)",
    ),
}


def documented_tools(text: str, start: str, end: str) -> set[str]:
    """Tool names in the bullet lines of the section between two headings."""
    section = text.split(start, 1)[1].split(end, 1)[0]
    bullets = "\n".join(line for line in section.splitlines() if line.startswith("- `"))
    return set(re.findall(r"`([a-z_]+)`", bullets))


async def test_docs_list_exactly_the_listed_tools_and_state_the_counts(mcp_server, monkeypatch):  # noqa: F811
    default = {tool.name for tool in await listed_tools(mcp_server)}
    monkeypatch.setenv(GITHUB_ENV_FLAG, "on")
    with_github = {tool.name for tool in await listed_tools(mcp_server)}

    for name, (start, end, count_pattern) in DOCS.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        assert documented_tools(text, start, end) == with_github, name
        stated = {tuple(int(number) for number in match) for match in re.findall(count_pattern, text)}
        assert stated == {(len(default), len(with_github))}, name
