"""Browse, filter and search every field in the page (REQ-0006-INTF-00, TASK-0093).

Two layers, tested separately. What the page contains - every record, every field, every comment - is rendered in
Python and read back here. What a reader sees after typing or choosing a filter is decided by two pure functions in
BROWSE_SCRIPT, which these tests run under node, so the logic is exercised rather than trusted. Node ships on the
GitHub runners this project's CI uses; where it is absent those tests skip rather than pass.
"""

import html
import json
import re
import shutil
import subprocess

import pytest

from lifecycle_mcp.viewer.browse import BROWSE_SCRIPT, search_text
from lifecycle_mcp.viewer.figures import derive_figures
from lifecycle_mcp.viewer.render import render_page
from lifecycle_mcp.viewer.snapshot import ReadOnlyDatabase, read_snapshot

from .test_next_tasks import add_task
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)
from .test_viewer_render import FIXED_TIME
from .test_viewer_snapshot import db_path

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed; the page's script cannot be run")


def page_for(server) -> str:
    path = db_path(server)
    snapshot = read_snapshot(path)
    return render_page(snapshot, derive_figures(snapshot, ReadOnlyDatabase(path)), FIXED_TIME)


def record_block(page: str, record_id: str) -> str:
    match = re.search(rf'<details class="record" id="{re.escape(record_id)}".*?</details>', page, re.DOTALL)
    assert match, f"{record_id} should be in the page"
    return match.group(0)


def run_script(harness: str) -> object:
    """Run BROWSE_SCRIPT plus a harness under node, returning whatever the harness prints as JSON."""
    completed = subprocess.run(
        [NODE, "-e", BROWSE_SCRIPT + "\n" + harness], capture_output=True, text=True, timeout=30, check=False
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


RECORDS_JS = """
var records = [
  { kind: "requirement", status: "Draft", priority: "P1", type: "FUNC",
    search: "req-1 search stays fast p95 under 50 ms at 10k notes" },
  { kind: "requirement", status: "Validated", priority: "P2", type: "NFUNC",
    search: "req-2 export resumes after a crash" },
  { kind: "task", status: "Not Started", priority: "P1", type: "", search: "task-1 build the index" },
  { kind: "decision", status: "Accepted", priority: "", type: "ADR", search: "adr-1 use sqlite fts5" },
];
"""


# --- what the page contains ----------------------------------------------------------------------


async def test_every_record_is_in_the_page_and_nothing_starts_hidden(mcp_server):  # noqa: F811
    """With scripting off the page must still show everything; the script only ever hides."""
    ids = await populate(mcp_server)
    second = await add_task(mcp_server, ids["requirement"], "Cache layer", "P2")

    page = page_for(mcp_server)

    for record_id in (ids["requirement"], ids["task"], second, ids["adr"]):
        # The attribute, not the word: the tag carries the record's search text, which may say "hidden".
        assert not re.search(r"\shidden(?:=|[\s>])", record_block(page, record_id).split(">", 1)[0] + ">"), record_id


async def test_a_record_reads_without_opening_it(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    summary = record_block(page_for(mcp_server), ids["requirement"]).split("</summary>")[0]

    for shown in (ids["requirement"], "Approved", "P1"):
        assert shown in summary, shown


async def test_opening_a_record_shows_every_field_it_holds(mcp_server):  # noqa: F811
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "NFUNC",
            "title": "Search stays fast",
            "priority": "P1",
            "current_state": "Unindexed; 900 ms at 10k notes.",
            "desired_state": "Quick as the collection grows.",
            "acceptance_criteria": ["p95 under 50 ms at 10k notes"],
            "validation_metrics": ["Search p95 under 50 ms, measured by the benchmark task"],
        },
    )
    requirement = result.structuredContent["id"]

    block = record_block(page_for(mcp_server), requirement)

    for value in ("Unindexed; 900 ms at 10k notes.", "p95 under 50 ms at 10k notes", "measured by the benchmark task"):
        assert html.escape(value) in block, value
    assert "Not filled:" in block and "out of scope" in block, "an empty field is named, not silently absent"


async def test_an_unreadable_field_shows_what_is_stored_and_says_so(mcp_server):  # noqa: F811
    import sqlite3

    ids = await populate(mcp_server)
    writer = sqlite3.connect(str(db_path(mcp_server)), timeout=30.0)
    try:
        writer.execute("UPDATE requirements SET out_of_scope = ? WHERE id = ?", ["[unterminated", ids["requirement"]])
        writer.commit()
    finally:
        writer.close()

    block = record_block(page_for(mcp_server), ids["requirement"])

    assert "not readable as the list this field should hold" in block
    assert "[unterminated" in block, "the stored text is shown, not replaced by an empty list"


async def test_comments_are_shown_with_their_record(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    assert not (
        await call(mcp_server, "add_comment", {"entity_id": ids["task"], "comment": "Blocked on review"})
    ).isError

    block = record_block(page_for(mcp_server), ids["task"])

    assert "Blocked on review" in block and "Comments (1)" in block


async def test_the_filters_offer_what_the_tracker_holds(mcp_server):  # noqa: F811
    await populate(mcp_server)

    page = page_for(mcp_server)

    status = re.search(r'<select id="filter-status".*?</select>', page, re.DOTALL).group(0)
    assert '<option value="Approved">' in status and '<option value="Not Started">' in status
    kind = re.search(r'<select id="filter-kind".*?</select>', page, re.DOTALL).group(0)
    assert all(f'<option value="{k}">' in kind for k in ("requirement", "task", "decision"))
    assert "<form" not in page, "controls without a form: nothing can be submitted anywhere"


async def test_search_reaches_a_term_the_server_search_cannot(mcp_server):  # noqa: F811
    """REQ-0003-NFUNC-00 measured search_text reaching 5.8% of a record. The page reaches all of it."""
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "Export survives interruption",
            "priority": "P2",
            "current_state": "An interrupted export starts over.",
            "desired_state": "Exports carry on where they stopped.",
            "acceptance_criteria": ["A checkpoint file records the last written chunk"],
        },
    )
    requirement = result.structuredContent["id"]

    server = await call(mcp_server, "query_requirements", {"search_text": "checkpoint"})
    assert not server.isError, text_of(server)
    assert server.structuredContent["count"] == 0, "the term is only in acceptance criteria, which search_text skips"

    block = record_block(page_for(mcp_server), requirement)
    assert "checkpoint" in html.unescape(re.search(r'data-search="(.*?)"', block).group(1))


def test_the_search_text_covers_nested_values_and_comments():
    record = {
        "id": "ADR-0001",
        "consequences": {"positive": ["Fast lookups"], "negative": ["A rebuild on schema change"]},
        "_unreadable": ["ignored"],
    }

    text = search_text(record, [{"comment": "Revisit After Launch"}])

    for term in ("adr-0001", "fast lookups", "rebuild on schema change", "revisit after launch"):
        assert term in text, term
    assert "ignored" not in text, "bookkeeping about the record is not part of what it says"


# --- what a reader sees (the script, under node) -------------------------------------------------


@needs_node
def test_each_filter_narrows_and_combined_filters_intersect():
    result = run_script(
        RECORDS_JS
        + """
function ids(state) { return records.filter(function (r) { return visible(r, state); }).map(function (r) {
  return r.search.split(" ")[0]; }); }
console.log(JSON.stringify({
  none: ids({}),
  kind: ids({ kind: "requirement" }),
  status: ids({ status: "Draft" }),
  priority: ids({ priority: "P1" }),
  type: ids({ type: "ADR" }),
  combined: ids({ kind: "requirement", priority: "P1" }),
  contradictory: ids({ kind: "task", type: "FUNC" }),
}));
"""
    )

    assert result == {
        "none": ["req-1", "req-2", "task-1", "adr-1"],
        "kind": ["req-1", "req-2"],
        "status": ["req-1"],
        "priority": ["req-1", "task-1"],
        "type": ["adr-1"],
        "combined": ["req-1"],
        "contradictory": [],
    }


@needs_node
def test_a_query_matches_when_every_word_appears_anywhere_in_the_record():
    """Unlike search_text, the words need not be adjacent: "export resume" finds "export resumes after a crash"."""
    result = run_script(
        RECORDS_JS
        + """
function ids(q) { return records.filter(function (r) { return visible(r, { query: q }); }).map(function (r) {
  return r.search.split(" ")[0]; }); }
console.log(JSON.stringify({ apart: ids("export resume"), cased: ids("SQLITE"), spaced: ids("  fts5   adr "),
  missing: ids("export index") }));
"""
    )

    assert result == {"apart": ["req-2"], "cased": ["adr-1"], "spaced": ["adr-1"], "missing": []}


@needs_node
def test_an_empty_result_says_which_case_it_is():
    """R17: silence is ambiguous. The page names the query that matched nothing, or the filter excluding everything."""
    result = run_script(
        RECORDS_JS
        + """
console.log(JSON.stringify({
  nothing: emptyReason([], {}),
  query: emptyReason(records, { query: "kubernetes" }),
  culprit: emptyReason(records, { kind: "task", type: "FUNC" }),
  status: emptyReason(records, { status: "Draft", priority: "P2" }),
}));
"""
    )

    assert result["nothing"] == "There are no records in this tracker."
    assert "kubernetes" in result["query"] and "in any field" in result["query"]
    assert "Clearing the kind or the type filter" in result["culprit"]
    assert "status" in result["status"] and "priority" in result["status"]


@needs_node
def test_the_script_does_nothing_without_a_document():
    """How this suite loads it: defining the functions must not touch a DOM that is not there."""
    assert run_script('console.log(JSON.stringify(typeof visible + " " + typeof emptyReason));') == "function function"


CHROME = next(
    (shutil.which(name) for name in ("google-chrome-stable", "google-chrome", "chromium") if shutil.which(name)), None
)


@pytest.mark.skipif(CHROME is None, reason="no headless Chrome; the page's DOM wiring cannot be exercised")
async def test_the_script_runs_in_a_real_browser(mcp_server, tmp_path):  # noqa: F811
    """The node tests cover the two pure functions; this covers init() wiring them to a real document.

    --dump-dom prints the DOM after scripts have run. The count line is rendered by Python as "N records" and only
    becomes "Showing N of N records" if init() found the records, bound the controls and ran apply() to the end.
    """
    await populate(mcp_server)
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
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert re.search(r'id="shown">Showing (\d+) of \1 records<', completed.stdout), "init() ran to completion"
    assert 'id="none" hidden' in completed.stdout, "with nothing typed, nothing reports an empty result"
