"""Browse, filter and search every record in the page (REQ-0006-INTF-00, TASK-0093).

Every record is rendered here, in Python, as a <details> element carrying its whole content. The page is therefore
complete and readable with scripting switched off; the script only hides and shows what is already there. That keeps
the JavaScript down to two pure functions - whether a record matches, and why nothing did - which the test suite runs
under node, so the part of the page that decides what a reader sees is tested rather than merely present.

Search covers every field. The server's search_text matches a substring of the title and desired state only, which is
5.8% of a stored requirement (REQ-0003-NFUNC-00); here each record carries a lowercased blob of every value it holds
and every comment on it, and a query matches when each of its words appears somewhere in that blob.
"""

import html
from collections import defaultdict
from typing import Any

from .links import link_index, links_html, record_titles
from .snapshot import UNREADABLE, Snapshot

# What the page calls each kind of record, and which snapshot rows are that kind.
ENTITY = {"project": "project", "requirement": "requirement", "task": "task", "decision": "architecture"}

KINDS: tuple[tuple[str, str, str], ...] = (
    ("project", "Projects", "projects"),
    ("requirement", "Requirements", "requirements"),
    ("task", "Tasks", "tasks"),
    ("decision", "Decisions", "architecture"),
)

# Shown in the summary line, so a list is readable without opening anything.
SUMMARY_FIELDS = ("id", "title", "status", "priority", "type", "effort")

# Bookkeeping the server maintains rather than content somebody wrote. Still shown - every field a record holds is on
# the page - but after the content, so it does not bury it.
BOOKKEEPING = (
    "project_number",
    "requirement_number",
    "task_number",
    "subtask_number",
    "version",
    "revision",
    "task_count",
    "tasks_completed",
    "created_at",
    "updated_at",
    "completed_at",
    "superseded_by",
    "github_issue_number",
    "github_issue_url",
    "github_etag",
    "github_last_sync",
)

BROWSE_STYLE = """
.controls { display: flex; flex-wrap: wrap; gap: .5rem; margin: .75rem 0; }
.controls input, .controls select {
  font: inherit; font-size: .875rem; color: var(--ink); background: var(--panel);
  border: 1px solid var(--line); border-radius: .375rem; padding: .375rem .5rem;
}
.controls input { flex: 1 1 14rem; min-width: 0; }
details.record { background: var(--panel); border: 1px solid var(--line); border-radius: .5rem; margin: 0 0 .5rem; }
details.record > summary { cursor: pointer; padding: .625rem .875rem; list-style-position: inside; }
details.record[open] > summary { border-bottom: 1px solid var(--line); }
.body { padding: .75rem .875rem; }
.body dl { margin: 0; display: grid; grid-template-columns: minmax(8rem, 12rem) 1fr; gap: .5rem .875rem; }
.body dt { color: var(--muted); font-size: .8125rem; }
.body dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.body dd ul { margin: 0; padding-left: 1.1rem; }
.body dd .text { margin: 0; white-space: pre-wrap; }
.body dd dl { grid-template-columns: minmax(5rem, 8rem) 1fr; }
.unfilled, .bookkeeping { color: var(--muted); font-size: .8125rem; margin: .75rem 0 0; }
.unreadable { color: var(--warn); }
.unreadable code { white-space: pre-wrap; }
.comments { margin: .875rem 0 0; padding: 0; list-style: none; display: grid; gap: .375rem; }
.comments li { border-left: 2px solid var(--line); padding-left: .625rem; font-size: .875rem; white-space: pre-wrap; }
.comments .who { color: var(--muted); font-size: .75rem; }
@media (max-width: 34rem) { .body dl { grid-template-columns: 1fr; gap: .125rem; } .body dt { margin-top: .5rem; } }
"""

# The only code in the page. Two pure functions decide everything a reader sees; init() wires them to the controls
# and does nothing when there is no document, which is how the test suite loads this under node.
BROWSE_SCRIPT = """
"use strict";
var FILTERS = { kind: "kind", status: "status", priority: "priority", type: "type", query: "search" };

function visible(record, state) {
  if (state.kind && record.kind !== state.kind) return false;
  if (state.status && record.status !== state.status) return false;
  if (state.priority && record.priority !== state.priority) return false;
  if (state.type && record.type !== state.type) return false;
  if (state.query) {
    var words = state.query.toLowerCase().split(/\\s+/).filter(Boolean);
    for (var i = 0; i < words.length; i++) {
      if (record.search.indexOf(words[i]) < 0) return false;
    }
  }
  return true;
}

function emptyReason(records, state) {
  var active = Object.keys(FILTERS).filter(function (key) { return state[key]; });
  if (!active.length) return "There are no records in this tracker.";
  if (state.query && !records.some(function (r) { return visible(r, { query: state.query }); })) {
    return "No record contains \\u201c" + state.query + "\\u201d in any field.";
  }
  var culprits = active.filter(function (key) {
    var without = Object.assign({}, state);
    without[key] = "";
    return records.some(function (r) { return visible(r, without); });
  });
  if (culprits.length) {
    return "Nothing matches all of these together. Clearing the " +
      culprits.map(function (key) { return FILTERS[key]; }).join(" or the ") + " filter would show records.";
  }
  return "Nothing matches these filters together, and no single filter is excluding everything on its own.";
}

function init() {
  var elements = Array.prototype.slice.call(document.querySelectorAll("details.record"));
  var records = elements.map(function (el) {
    return { el: el, kind: el.dataset.kind, status: el.dataset.status, priority: el.dataset.priority,
             type: el.dataset.type, search: el.dataset.search };
  });
  var controls = ["query", "kind", "status", "priority", "type"].map(function (key) {
    return document.getElementById("filter-" + key);
  });
  var shown = document.getElementById("shown");
  var none = document.getElementById("none");

  function apply() {
    var state = {};
    controls.forEach(function (control) { state[control.dataset.filter] = control.value.trim(); });
    var count = 0;
    records.forEach(function (r) {
      var show = visible(r, state);
      r.el.hidden = !show;
      if (show) count++;
    });
    document.querySelectorAll("section.kind").forEach(function (section) {
      var visibleHere = section.querySelectorAll("details.record:not([hidden])").length;
      section.hidden = visibleHere === 0;
      section.querySelector(".kind-count").textContent = visibleHere;
    });
    shown.textContent = "Showing " + count + " of " + records.length + " records";
    none.hidden = count !== 0;
    none.textContent = count === 0 ? emptyReason(records, state) : "";
  }

  // Following a link opens the record it points at. If the filters are hiding it, clear them first: a link that
  // leads to nothing visible reads as a broken one.
  function reveal() {
    var id = decodeURIComponent(location.hash.slice(1));
    var target = id && document.getElementById(id);
    if (!target || !target.classList.contains("record")) return;
    if (target.hidden) {
      controls.forEach(function (control) { control.value = ""; });
      apply();
    }
    target.open = true;
    target.scrollIntoView();
  }

  controls.forEach(function (control) { control.addEventListener("input", apply); });
  window.addEventListener("hashchange", reveal);
  apply();
  reveal();
}

if (typeof document !== "undefined") init();
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def label(column: str) -> str:
    """A column name as a reader would say it."""
    return column.replace("_", " ").capitalize()


def _flatten(value: Any) -> list[str]:
    """Every piece of text inside a stored value, however it is nested."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in (str(key), *_flatten(item))]
    if isinstance(value, list):
        return [text for item in value for text in _flatten(item)]
    return [str(value)]


def search_text(record: dict[str, Any], comments: list[dict[str, Any]]) -> str:
    """Every field a record holds and every comment on it, lowercased, for the page's search to match against."""
    parts = [text for key, value in record.items() if key != UNREADABLE for text in _flatten(value)]
    parts += [str(comment.get("comment") or "") for comment in comments]
    return " ".join(" ".join(parts).lower().split())


def _value(column: str, value: Any, record: dict[str, Any]) -> str:
    """One field's value as markup. Lists as lists, objects as definition lists, text with its line breaks."""
    if column in record.get(UNREADABLE, ()):
        return (
            f'<p class="unreadable">Stored, but not readable as the list this field should hold:<br>'
            f"<code>{_esc(value)}</code></p>"
        )
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_value(column, item, {})}</li>" for item in value) + "</ul>"
    if isinstance(value, dict):
        rows = "".join(
            f"<dt>{_esc(label(str(key)))}</dt><dd>{_value(column, item, {})}</dd>" for key, item in value.items()
        )
        return f"<dl>{rows}</dl>"
    return f'<p class="text">{_esc(value)}</p>'


def _filled(value: Any) -> bool:
    return value not in (None, "", [], {})


def record_details(kind: str, record: dict[str, Any], comments: list[dict[str, Any]], links: str = "") -> str:
    """One record: a summary line readable without opening it, then every field it holds, then its comments."""
    pills = "".join(
        f'<span class="pill">{_esc(record[key])}</span>'
        for key in ("status", "priority", "type", "effort")
        if record.get(key)
    )
    content_columns = [column for column in record if column not in (*SUMMARY_FIELDS[:2], *BOOKKEEPING, UNREADABLE)]
    filled = [column for column in content_columns if _filled(record[column])]
    unfilled = [column for column in content_columns if not _filled(record[column])]

    fields = "".join(
        f"<dt>{_esc(label(column))}</dt><dd>{_value(column, record[column], record)}</dd>" for column in filled
    )
    body = f"<dl>{fields}</dl>" if fields else ""
    if unfilled:
        body += f'<p class="unfilled">Not filled: {_esc(", ".join(label(c).lower() for c in unfilled))}</p>'
    body += links
    if comments:
        items = "".join(
            f'<li><div class="who">{_esc(comment.get("reviewer") or "Someone")}, '
            f"{_esc(comment.get('created_at'))}</div>"
            f"{_esc(comment.get('comment'))}</li>"
            for comment in comments
        )
        body += f'<p class="bookkeeping">Comments ({len(comments)})</p><ul class="comments">{items}</ul>'
    kept = [f"{label(column)}: {record[column]}" for column in BOOKKEEPING if _filled(record.get(column))]
    if kept:
        body += f'<p class="bookkeeping">{_esc(" · ".join(kept))}</p>'

    data = {
        "kind": kind,
        "status": record.get("status") or "",
        "priority": record.get("priority") or "",
        "type": record.get("type") or "",
        "search": search_text(record, comments),
    }
    attributes = " ".join(f'data-{key}="{_esc(value)}"' for key, value in data.items())
    return (
        f'<details class="record" id="{_esc(record.get("id"))}" {attributes}>'
        f'<summary><span class="id">{_esc(record.get("id"))}</span> '
        f'<span class="title">{_esc(record.get("title"))}</span> {pills}</summary>'
        f'<div class="body">{body}</div></details>'
    )


def _options(control: str, values: list[str], everything: str) -> str:
    options = f'<option value="">{_esc(everything)}</option>' + "".join(
        f'<option value="{_esc(value)}">{_esc(value)}</option>' for value in values
    )
    return f'<select id="filter-{control}" data-filter="{control}" aria-label="{_esc(everything)}">{options}</select>'


def browse_section(snapshot: Snapshot) -> str:
    """The records, every one of them, with the controls that narrow them."""
    comments_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for comment in snapshot.comments:
        comments_by_entity[str(comment.get("entity_id"))].append(comment)

    index, known = link_index(snapshot), record_titles(snapshot)
    groups = []
    every: list[dict[str, Any]] = []
    for kind, heading, attribute in KINDS:
        rows = getattr(snapshot, attribute)
        every += rows
        items = "".join(
            record_details(
                kind,
                row,
                comments_by_entity.get(str(row.get("id")), []),
                links_html(str(row.get("id")), ENTITY[kind], index, known),
            )
            for row in rows
        )
        groups.append(
            f'<section class="kind" id="records-{kind}"><h2>{_esc(heading)} '
            f'<span class="pill kind-count">{len(rows)}</span></h2>{items}</section>'
        )

    def distinct(column: str) -> list[str]:
        return sorted({str(row[column]) for row in every if row.get(column)})

    controls = (
        '<input type="search" id="filter-query" data-filter="query" '
        'placeholder="Search every field and comment" aria-label="Search">'
        + _options("kind", [kind for kind, _, _ in KINDS], "All kinds")
        + _options("status", distinct("status"), "Any status")
        + _options("priority", distinct("priority"), "Any priority")
        + _options("type", distinct("type"), "Any type")
    )
    total = len(every)
    return (
        '<section id="records"><h2>Records</h2>'
        '<p class="why">Every project, requirement, task and decision, with every field it holds. '
        "Search matches every field and every comment, not only titles.</p>"
        f'<div class="controls">{controls}</div>'
        f'<p class="sub" id="shown">{total} records</p>'
        '<div class="empty" id="none" hidden></div>' + "".join(groups) + "</section>"
    )
