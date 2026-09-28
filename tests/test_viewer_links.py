"""A record's links from its own end, navigable within the page (REQ-0006-INTF-00, TASK-0094).

The page groups links by type and direction the way query_relationships does, and keeps the tool's arrows, so the
central test here reads both and compares them record by record. The headings are get_details' where it has one, which
matters for implements: its direction convention flips with the pair, so a heading has to know which kind of record it
sits on.
"""

import re
import shutil
import subprocess

import pytest

from lifecycle_mcp.viewer.figures import derive_figures
from lifecycle_mcp.viewer.links import heading, links_html
from lifecycle_mcp.viewer.render import render_page
from lifecycle_mcp.viewer.snapshot import ReadOnlyDatabase, read_snapshot

from .test_next_tasks import add_task, link
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)
from .test_viewer_render import FIXED_TIME
from .test_viewer_snapshot import db_path


def page_for(server) -> str:
    path = db_path(server)
    snapshot = read_snapshot(path)
    return render_page(snapshot, derive_figures(snapshot, ReadOnlyDatabase(path)), FIXED_TIME)


def record_block(page: str, record_id: str) -> str:
    match = re.search(rf'<details class="record" id="{re.escape(record_id)}".*?</details>', page, re.DOTALL)
    assert match, record_id
    return match.group(0)


def page_links(page: str, record_id: str) -> dict[str, set[tuple[str, str]]]:
    """A record's links as the page shows them: type -> {(arrow, other id)}."""
    found: dict[str, set[tuple[str, str]]] = {}
    block = record_block(page, record_id)
    for kind, items in re.findall(r'<h3 data-type="([^"]+)" data-direction="[^"]+">.*?</h3><ul>(.*?)</ul>', block):
        for arrow, other in re.findall(r'<span class="arrow">(.)</span><(?:a|span) class="id"[^>]*>([^<]+)<', items):
            found.setdefault(kind, set()).add((arrow, other))
    return found


async def tool_links(server, record_id: str) -> dict[str, set[tuple[str, str]]]:
    """The same record's links as query_relationships reports them."""
    result = await call(server, "query_relationships", {"entity_id": record_id})
    assert not result.isError, text_of(result)
    found: dict[str, set[tuple[str, str]]] = {}
    kind = None
    for line in text_of(result).splitlines():
        section = re.match(r"^## (\w+) \(\d+\)$", line)
        if section:
            kind = section.group(1).lower()
            continue
        entry = re.match(r"^- ([→←]) \*\*.*\*\* \((\S+)\)$", line)
        if entry and kind:
            found.setdefault(kind, set()).add((entry.group(1), entry.group(2)))
    return found


async def linked_tracker(server) -> dict[str, str]:
    """Every kind of link the tools make: implements both ways, addresses, depends, parent and supersedes."""
    ids = await populate(server)
    api = await add_task(server, ids["requirement"], "API", "P1")
    await link(server, api, ids["task"], "depends")
    await link(server, api, ids["adr"], "implements")
    child = await call(
        server,
        "create_task",
        {
            "requirement_ids": [ids["requirement"]],
            "title": "Tokenizer",
            "priority": "P2",
            "parent_task_id": ids["task"],
        },
    )
    assert not child.isError, text_of(child)
    newer = await call(
        server,
        "create_architecture_decision",
        {
            "requirement_ids": [ids["requirement"]],
            "title": "Use FTS5 trigram",
            "context": "Substrings",
            "decision": "x",
        },
    )
    assert not newer.isError, text_of(newer)
    newer_id = newer.structuredContent["id"] if newer.structuredContent else "ADR-0002"
    await link(server, newer_id, ids["adr"], "supersedes")
    return {**ids, "api": api, "child": child.structuredContent["id"], "newer": newer_id}


# --- agreement with the tool ---------------------------------------------------------------------


async def test_every_records_links_agree_with_query_relationships(mcp_server):  # noqa: F811
    ids = await linked_tracker(mcp_server)
    page = page_for(mcp_server)

    compared: set[str] = set()
    for record_id in ids.values():
        from_tool = await tool_links(mcp_server, record_id)
        assert page_links(page, record_id) == from_tool, record_id
        compared |= set(from_tool)

    # Both sides parsing nothing would compare equal; this is what makes the loop above a check of something.
    assert compared >= {"implements", "addresses", "depends", "parent", "supersedes"}, compared


# --- navigation ----------------------------------------------------------------------------------


async def test_every_link_lands_on_a_record_in_the_page(mcp_server):  # noqa: F811
    await linked_tracker(mcp_server)
    page = page_for(mcp_server)

    records = set(re.findall(r'<details class="record" id="([^"]+)"', page))
    targets = [target[1:] for target in re.findall(r'<a class="id" href="([^"]+)"', page)]

    assert targets and set(targets) <= records


async def test_a_link_is_navigable_from_both_ends(mcp_server):  # noqa: F811
    ids = await linked_tracker(mcp_server)
    page = page_for(mcp_server)

    requirement = record_block(page, ids["requirement"])
    decision = record_block(page, ids["adr"])

    assert "Addresses decisions" in requirement and f'href="#{ids["adr"]}"' in requirement
    assert "Linked requirements" in decision and f'href="#{ids["requirement"]}"' in decision


async def test_the_dashboard_links_to_the_records_it_names(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    dashboard = page_for(mcp_server).split('<section id="records">')[0]

    assert f'<a class="id" href="#{ids["task"]}">' in dashboard, "the ready task on the dashboard opens its record"


# --- headings ------------------------------------------------------------------------------------


async def test_parent_and_supersedes_keep_their_own_headings(mcp_server):  # noqa: F811
    ids = await linked_tracker(mcp_server)
    page = page_for(mcp_server)

    assert "Subtasks (1)" in record_block(page, ids["task"])
    assert "Parent task (1)" in record_block(page, ids["child"])
    assert "Supersedes (1)" in record_block(page, ids["newer"])
    assert "Superseded by (1)" in record_block(page, ids["adr"])


def test_implements_is_named_for_the_kind_of_record_it_sits_on():
    """requirement -> task has the target implementing; task -> architecture has the source implementing."""
    assert heading("implements", "out", "requirement") == "Linked tasks"
    assert heading("implements", "in", "task") == "Linked requirements"
    assert heading("implements", "out", "task") == "Implements decisions"
    assert heading("implements", "in", "architecture") == "Implemented by"


def test_an_unfamiliar_link_falls_back_to_its_type_and_the_tools_arrow():
    assert heading("mentors", "out", "task") == "Mentors →"
    assert heading("mentors", "in", "task") == "Mentors ←"


# --- absence -------------------------------------------------------------------------------------


async def test_a_record_with_no_links_shows_no_links_section(mcp_server):  # noqa: F811
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "Alone",
            "priority": "P3",
            "current_state": "Nothing links here.",
            "desired_state": "Still nothing.",
        },
    )

    block = record_block(page_for(mcp_server), result.structuredContent["id"])

    assert '<div class="links">' not in block


def test_a_link_to_a_record_the_page_does_not_hold_is_named_not_linked():
    html_out = links_html(
        "TASK-0001-00-00", "task", {"TASK-0001-00-00": [("depends", "out", "TASK-0404-00-00")]}, {"TASK-0001-00-00": {}}
    )

    assert "TASK-0404-00-00" in html_out and "not in this tracker" in html_out
    assert 'href="#TASK-0404-00-00"' not in html_out, "a link that leads nowhere reads as a broken one"


# --- following a link, in a real browser ---------------------------------------------------------

CHROME = next(
    (shutil.which(name) for name in ("google-chrome-stable", "google-chrome", "chromium") if shutil.which(name)), None
)


@pytest.mark.skipif(CHROME is None, reason="no headless Chrome; following a link cannot be exercised")
async def test_arriving_at_a_records_anchor_opens_it(mcp_server, tmp_path):  # noqa: F811
    ids = await linked_tracker(mcp_server)
    # A record whose text says "open": each record's tag carries its search text, so a check that looked for the word
    # rather than the attribute would count this one as opened. It did, 36 times over, on this repository's tracker.
    decoy = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "Open tasks stay open",
            "priority": "P3",
            "current_state": "An open task is open until it closes.",
            "desired_state": "Still open.",
        },
    )
    assert not decoy.isError, text_of(decoy)
    page = tmp_path / "tracker.html"
    page.write_text(page_for(mcp_server), encoding="utf-8")

    completed = subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            f"--user-data-dir={tmp_path / 'profile'}",
            "--dump-dom",
            f"{page.as_uri()}#{ids['api']}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    tags = re.findall(r'<details class="record"[^>]*>', completed.stdout)
    opened = [re.search(r'id="([^"]+)"', tag).group(1) for tag in tags if re.search(r'\sopen=""', tag)]
    assert opened == [ids["api"]], "the record the anchor names is open, and only that one"
