"""One self-contained HTML file that works offline (REQ-0006-INTF-00, TASK-0092).

The properties worth pinning are the ones that make the file worth having: it opens from a filesystem with nothing
installed, it reaches for nothing on a network, and it cannot write. The first two are testable by reading the output;
the third is testable because the page has no database in it to write to.
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lifecycle_mcp.viewer.browse import BROWSE_SCRIPT
from lifecycle_mcp.viewer.figures import derive_figures
from lifecycle_mcp.viewer.render import project_name, render_page, write_page
from lifecycle_mcp.viewer.snapshot import ReadOnlyDatabase, read_snapshot

from .test_next_tasks import add_task, link, move
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)
from .test_viewer_snapshot import db_path

FIXED_TIME = datetime(2026, 9, 28, 15, 30, tzinfo=timezone(timedelta(hours=-4), "EDT"))


def page_for(server, generated_at: datetime | None = FIXED_TIME) -> str:
    path = db_path(server)
    snapshot = read_snapshot(path)
    return render_page(snapshot, derive_figures(snapshot, ReadOnlyDatabase(path)), generated_at)


def record_ids(page: str) -> list[str]:
    """The records the page renders, in order."""
    return re.findall(r'<details class="record" id="([^"]+)"', page)


# --- self-contained ------------------------------------------------------------------------------


WRITE_PATH = ("fetch(", "XMLHttpRequest", "<form", "WebAssembly", "serviceWorker", "sql.js", "localStorage", "url(")


async def test_the_page_loads_nothing_from_a_network(mcp_server):  # noqa: F811
    await populate(mcp_server)
    page = page_for(mcp_server)

    assert not re.search(r"\b(src|action)\s*=", page), "nothing is fetched, not even locally"
    # The only links are anchors to records the page itself holds (TASK-0094).
    targets = re.findall(r'href="([^"]*)"', page)
    assert targets, "links exist, so this is checking something"
    assert all(target.startswith("#") for target in targets), [t for t in targets if not t.startswith("#")]
    assert {target[1:] for target in targets} <= set(record_ids(page)), "every link lands on a record in the page"
    assert "<link" not in page, "no external stylesheet"
    assert "@import" not in page
    assert "//fonts." not in page


async def test_with_no_records_the_page_names_no_host_and_holds_no_write_path(mcp_server):  # noqa: F811
    """Render a tracker with nothing in it and every byte left is the viewer's own choice.

    Asserting this against a populated page stopped working twice: first because TASK-0092's own test plan, stored in
    this repository's tracker, contains "http://" and "XMLHttpRequest"; then because records are now rendered as text
    in the page body, not only in the data block, so a record that quotes a link legitimately puts one there. What a
    record says is its own business. What the viewer adds must name no host and reach for nothing.
    """
    page = page_for(mcp_server)

    assert "http://" not in page and "https://" not in page
    for forbidden in WRITE_PATH:
        assert forbidden not in page, forbidden


def test_the_only_code_the_page_runs_holds_no_write_path():
    """The page runs BROWSE_SCRIPT and nothing else; the injection test pins that no record can add a block."""
    for forbidden in WRITE_PATH:
        assert forbidden not in BROWSE_SCRIPT, forbidden
    assert "innerHTML" not in BROWSE_SCRIPT, "text the page writes goes through textContent, never parsed as markup"


async def test_a_record_that_quotes_a_link_keeps_it_as_text(mcp_server):  # noqa: F811
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "A requirement that quotes a link",
            "priority": "P3",
            "current_state": "Documented at https://example.com/spec today.",
            "desired_state": "Still documented there.",
        },
    )
    assert not result.isError, text_of(result)

    page = page_for(mcp_server)

    assert "https://example.com/spec" in page, "a record's own text is preserved, URLs included"
    assert not re.search(r"(src|href|action)\s*=\s*\"?https://example", page), "as text, never as something to load"


async def test_the_page_stands_on_its_own_as_a_document(mcp_server):  # noqa: F811
    page = page_for(mcp_server)

    assert page.startswith("<!DOCTYPE html>")
    assert "<style>" in page, "styling is inline, so the file is the whole thing"
    assert '<meta name="viewport"' in page, "readable at phone width"
    assert "prefers-color-scheme: dark" in page, "legible in both colour schemes"
    assert page.rstrip().endswith("</html>")


async def test_the_page_names_when_it_was_generated(mcp_server):  # noqa: F811
    page = page_for(mcp_server)

    assert "Snapshot generated 2026-09-28 15:30" in page, "a snapshot has to say how stale it is"


async def test_two_runs_differ_only_in_the_generation_time(mcp_server):  # noqa: F811
    await populate(mcp_server)
    later = FIXED_TIME + timedelta(hours=3)

    first = page_for(mcp_server, FIXED_TIME)
    second = page_for(mcp_server, later)

    assert first != second
    assert first.replace("2026-09-28 15:30", "").replace("18:30", "") == second.replace("2026-09-28 18:30", "").replace(
        "15:30", ""
    ), "nothing else about an unchanged tracker should move"


async def test_the_same_tracker_renders_identically_twice(mcp_server):  # noqa: F811
    """With the time held still, the page is byte-stable, so a diff shows only what the tracker did."""
    await populate(mcp_server)

    assert page_for(mcp_server, FIXED_TIME) == page_for(mcp_server, FIXED_TIME)


# --- what it shows -------------------------------------------------------------------------------


async def test_every_record_travels_with_the_page(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    second = await add_task(mcp_server, ids["requirement"], "Cache layer", "P2")

    page = page_for(mcp_server)

    assert set(record_ids(page)) == {ids["requirement"], ids["task"], second, ids["adr"]}
    assert '<div class="links">' in page, "the links come too, rendered on the records they join"


async def test_the_page_carries_no_second_copy_of_the_records(mcp_server):  # noqa: F811
    """The records once also travelled as a JSON block for the browse and link views to read. Both render their content
    as markup instead, so the page reads with scripting off, and the block was 37% of the file with nothing reading it
    (417 KB of 1.1 MB on this repository's tracker). Removed in TASK-0094; this keeps it from coming back unread."""
    await populate(mcp_server)

    page = page_for(mcp_server)

    assert "application/json" not in page


async def test_the_dashboard_signals_appear_with_their_records(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    waiting = await add_task(mcp_server, ids["requirement"], "API", "P1")
    await link(mcp_server, waiting, ids["task"], "depends")

    page = page_for(mcp_server)

    assert "Blocked and waiting" in page
    assert waiting in page and f"Waiting on {ids['task']}" in page
    assert "Ready to start" in page and ids["task"] in page


async def test_an_empty_section_says_which_case_it_is(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await move(mcp_server, ids["task"], "Complete")

    page = page_for(mcp_server)

    assert "every task is Complete or Abandoned" in page, "not merely an empty list"
    assert "Work complete, decision pending" in page and ids["requirement"] in page


async def test_counts_are_shown_as_tiles(mcp_server):  # noqa: F811
    await populate(mcp_server)

    page = page_for(mcp_server)

    assert "requirements</div>" in page and "decisions</div>" in page
    assert "Requirements by status" in page and "Tasks by status" in page


# --- escaping ------------------------------------------------------------------------------------


async def test_a_record_cannot_inject_markup_into_the_page(mcp_server):  # noqa: F811
    """A title is text. If it could close a tag, any tracker could rewrite its own viewer."""
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "<script>alert('x')</script> & <b>bold</b>",
            "priority": "P2",
            "current_state": "Contains markup.",
            "desired_state": "Rendered as text.",
        },
    )
    assert not result.isError, text_of(result)

    page = page_for(mcp_server)

    assert "<script>alert" not in page
    assert "&lt;script&gt;alert" in page or "\\u003cscript\\u003ealert" in page
    # Exactly the one block the page defines itself - its browsing code - and none opened by a record.
    opened = re.findall(r"<script[^>]*>", page)
    assert opened == ['<script id="tracker-browse">'], opened


# --- writing it out -----------------------------------------------------------------------------


async def test_writing_the_page_creates_the_directory_and_returns_the_path(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)
    path = db_path(mcp_server)
    snapshot = read_snapshot(path)
    destination = tmp_path / "exports" / "tracker.html"

    written = write_page(snapshot, derive_figures(snapshot, ReadOnlyDatabase(path)), destination, FIXED_TIME)

    assert written == destination and destination.exists()
    assert destination.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_the_project_is_named_after_the_directory_holding_the_database(tmp_path):
    assert project_name(str(tmp_path / "quire" / "lifecycle.db")) == "quire"
    assert project_name("lifecycle.db"), "never empty, even with no directory"


async def test_the_page_is_readable_without_python_or_the_server(mcp_server, tmp_path):  # noqa: F811
    """The file is the deliverable: nothing about it depends on this project being installed where it is read."""
    await populate(mcp_server)
    path = db_path(mcp_server)
    snapshot = read_snapshot(path)
    destination = write_page(snapshot, derive_figures(snapshot, ReadOnlyDatabase(path)), tmp_path / "t.html")

    moved = Path(tmp_path / "elsewhere.html")
    moved.write_bytes(destination.read_bytes())
    destination.unlink()

    page = moved.read_text(encoding="utf-8")
    assert Path(snapshot.database_path).name in page, "it still says where it came from"
    assert record_ids(page), "and it still holds the records, with the database gone from beside it"
