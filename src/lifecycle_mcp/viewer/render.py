"""Emit one self-contained HTML file that works offline (REQ-0006-INTF-00, TASK-0092).

Everything the page needs is in the page: every record rendered as markup, the styling inline, and no reference to
anything on a network. A browser will not fetch a local .db from a file:// document, so the alternative was SQLite
compiled to WASM plus a file picker - a megabyte of wasm, an extra step for the reader, and handing over the database
itself. Rendering the records costs a regeneration when the tracker changes, which a snapshot needs anyway, and buys a
file that opens by double-clicking on a machine that has never had this project installed.

The page once also carried every record a second time as a JSON block, for the browsing and link views to read. Both
were built to render their content here instead, so the page reads with scripting off, and the block became 37% of the
file with nothing reading it. It was removed in TASK-0094.

The page holds no write path at all. There is no form, no fetch, no XMLHttpRequest and no database in it, so opening it
cannot change a tracker - and could not even if it tried, because the tracker is not there. The only links are anchors
to records within the page.

Deliberately not byte-deterministic: the page states when it was generated, which a snapshot needs and a tracked file
cannot have. That is the opposite of the text dump in REQ-0007-TECH-00, and the two can differ because this output is a
build artefact that is never committed.
"""

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from .browse import BROWSE_SCRIPT, BROWSE_STYLE, browse_section
from .figures import Figures
from .links import LINKS_STYLE
from .snapshot import Snapshot

# Everything the page shows about a record kind, so the sections below stay declarative.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("blocked", "Blocked and waiting", "Tasks that are Blocked, or waiting on work that is not finished"),
    ("work_complete", "Work complete, decision pending", "Every task finished, and the requirement not yet moved"),
    ("ready", "Ready to start", "Not Started, and everything they wait on is Complete"),
    ("stale", "Needs verification", "Changed since anyone last checked, or unchecked for longer than the threshold"),
    ("changed_since_review", "Changed since last review", "Reviewed requirements edited since their last status move"),
)

STYLE = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfa; --panel: #ffffff; --ink: #1a1a18; --muted: #63635e; --line: #e4e4de;
  --accent: #3a5f8a; --warn: #8a5a1a; --ok: #2f6a45;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #17181a; --panel: #1f2023; --ink: #e8e8e4; --muted: #9a9a94; --line: #323337;
    --accent: #8fb3d9; --warn: #d9ab6a; --ok: #7fc09a;
  }
}
:root[data-theme="dark"] {
  --bg: #17181a; --panel: #1f2023; --ink: #e8e8e4; --muted: #9a9a94; --line: #323337;
  --accent: #8fb3d9; --warn: #d9ab6a; --ok: #7fc09a;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font);
  line-height: 1.5; -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 68rem; margin: 0 auto; padding: 2rem 1rem 4rem; }
header h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
.sub { color: var(--muted); font-size: .875rem; margin: 0; }
.sub code { font-family: var(--mono); font-size: .8125rem; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: .75rem; margin: 1.5rem 0; }
.tile { background: var(--panel); border: 1px solid var(--line); border-radius: .5rem; padding: .75rem .875rem; }
.tile .n { font-size: 1.5rem; font-variant-numeric: tabular-nums; }
.tile .k { color: var(--muted); font-size: .75rem; text-transform: uppercase; letter-spacing: .04em; }
section { margin: 2rem 0 0; }
section h2 { font-size: 1.0625rem; margin: 0 0 .125rem; }
section .why { color: var(--muted); font-size: .8125rem; margin: 0 0 .75rem; }
.empty {
  background: var(--panel); border: 1px dashed var(--line); border-radius: .5rem;
  padding: .75rem .875rem; color: var(--muted); font-size: .875rem;
}
ul.rows { list-style: none; margin: 0; padding: 0; display: grid; gap: .5rem; }
ul.rows li { background: var(--panel); border: 1px solid var(--line); border-radius: .5rem; padding: .625rem .875rem; }
.id { font-family: var(--mono); font-size: .8125rem; color: var(--accent); }
.title { font-weight: 500; }
.meta { color: var(--muted); font-size: .8125rem; margin-top: .125rem; }
.pill {
  display: inline-block; border: 1px solid var(--line); border-radius: 1rem;
  padding: 0 .5rem; font-size: .75rem; color: var(--muted);
}
.bars { display: grid; gap: .375rem; margin: 0; }
.bar { display: grid; grid-template-columns: 8rem 1fr 3rem; gap: .5rem; align-items: center; font-size: .8125rem; }
.bar .track { background: var(--line); border-radius: 1rem; height: .5rem; overflow: hidden; }
.bar .fill { background: var(--accent); height: 100%; }
.bar .n { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
footer {
  margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: .8125rem;
}
@media (max-width: 34rem) {
  .wrap { padding: 1.25rem 1rem 3rem; }
  .bar { grid-template-columns: 6.5rem 1fr 2.5rem; }
}
"""


def _esc(value: Any) -> str:
    """Text that cannot close a tag or open one."""
    return html.escape("" if value is None else str(value), quote=True)


def _tile(count: int, label: str) -> str:
    return f'<div class="tile"><div class="n">{count}</div><div class="k">{_esc(label)}</div></div>'


def _bars(counts: dict[str, int], heading: str) -> str:
    if not counts:
        return ""
    total = max(sum(counts.values()), 1)
    rows = "".join(
        f'<div class="bar"><div>{_esc(name)}</div>'
        f'<div class="track"><div class="fill" style="width:{count / total * 100:.1f}%"></div></div>'
        f'<div class="n">{count}</div></div>'
        for name, count in counts.items()
    )
    return f'<section><h2>{_esc(heading)}</h2><div class="bars">{rows}</div></section>'


def _row(entry: dict[str, Any], section: str) -> str:
    """One record in a signal section. Kept to what the figures decided; the page adds no judgement of its own."""
    pills = "".join(
        f'<span class="pill">{_esc(entry[key])}</span>' for key in ("status", "priority", "effort") if entry.get(key)
    )
    meta = ""
    if section == "blocked":
        if entry.get("waiting_on"):
            meta = f"Waiting on {_esc(', '.join(entry['waiting_on']))}"
        if entry.get("abandoned"):
            meta = (meta + " · " if meta else "") + f"Abandoned dependencies: {_esc(', '.join(entry['abandoned']))}"
        if entry.get("blocked_reason"):
            meta = (meta + " · " if meta else "") + f"Reason: {_esc(entry['blocked_reason'])}"
    elif section == "stale":
        why = "content changed since the last check" if entry.get("stale_reason") == "changed" else "unchecked"
        meta = f"{why} · last checked {_esc(entry.get('verified_at'))} ({_esc(entry.get('age'))})"
    elif section == "changed_since_review":
        meta = f"edited {_esc(', '.join(entry.get('fields') or []))} at {_esc(entry.get('edited_at'))}"
    elif section == "work_complete":
        count = entry.get("task_count") or 0
        meta = f"{count} task{'s' if count != 1 else ''} complete, awaiting a decision"
    return (
        f'<li><a class="id" href="#{_esc(entry.get("id"))}">{_esc(entry.get("id"))}</a> '
        f'<span class="title">{_esc(entry.get("title"))}</span> {pills}'
        + (f'<div class="meta">{meta}</div>' if meta else "")
        + "</li>"
    )


def _section(key: str, heading: str, description: str, figures: Figures) -> str:
    rows = getattr(figures, key)
    body = (
        f'<ul class="rows">{"".join(_row(dict(entry), key) for entry in rows)}</ul>'
        if rows
        # An empty section says which case it is rather than nothing at all (roadmap R17).
        else f'<div class="empty">{_esc(figures.empty_reasons.get(key, "Nothing to show."))}</div>'
    )
    return (
        f'<section><h2>{_esc(heading)} <span class="pill">{len(rows)}</span></h2>'
        f'<p class="why">{_esc(description)}</p>{body}</section>'
    )


def project_name(database_path: str) -> str:
    """What to call the tracker: the directory holding the database, which is the project in every layout so far."""
    path = Path(database_path)
    return path.parent.name or path.stem or "Lifecycle"


def render_page(snapshot: Snapshot, figures: Figures, generated_at: datetime | None = None) -> str:
    """One self-contained HTML document: the whole tracker, styled, with nothing fetched from anywhere."""
    generated = (generated_at or datetime.now().astimezone()).strftime("%Y-%m-%d %H:%M %Z").strip()
    name = project_name(snapshot.database_path)
    counts = snapshot.counts()

    tiles = "".join(
        _tile(counts[key], label)
        for key, label in (
            ("requirements", "requirements"),
            ("tasks", "tasks"),
            ("architecture", "decisions"),
            ("relationships", "links"),
            ("comments", "comments"),
            ("events", "events"),
        )
    )
    signal_sections = "".join(_section(key, heading, why, figures) for key, heading, why in SECTIONS)
    return f"""<!DOCTYPE html>
<html lang="en" >
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(name)} tracker</title>
<style>{STYLE}{BROWSE_STYLE}{LINKS_STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{_esc(name)} tracker</h1>
  <p class="sub">Snapshot generated {_esc(generated)} from <code>{_esc(snapshot.database_path)}</code>.
  Read-only: this page is a copy, and nothing here can change the tracker.</p>
</header>
<div class="tiles">{tiles}</div>
{signal_sections}
{_bars(figures.requirements_by_status, "Requirements by status")}
{_bars(figures.tasks_by_status, "Tasks by status")}
{_bars(figures.architecture_by_status, "Decisions by status")}
{browse_section(snapshot)}
<footer>
  Generated by lifecycle-mcp's viewer. A snapshot of one moment: regenerate it to see later changes.
  Every figure above comes from the definitions the server's own tools use.
</footer>
</div>
<script id="tracker-browse">{BROWSE_SCRIPT}</script>
</body>
</html>
"""


def write_page(
    snapshot: Snapshot, figures: Figures, output_path: str | Path, generated_at: datetime | None = None
) -> Path:
    """Render and write the page, returning where it landed."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_page(snapshot, figures, generated_at), encoding="utf-8")
    return destination
