"""A record's links, shown from its own end and navigable within the page (REQ-0006-INTF-00, TASK-0094).

Links are grouped by type and direction the way query_relationships groups them, and every entry keeps the tool's own
arrow - → where this record is the source, ← where it is the target - so the page and the tool can be read against
each other. The headings are the ones get_details already uses where it has one. They cannot be derived from the
relationship type alone, because the direction convention for implements depends on the pair: in requirement → task
the target does the implementing, in task → architecture the source does. So a heading is looked up by the link's type,
its direction and the kind of record it is shown on, and falls back to the type and the arrow.

Every link is an in-page anchor. Nothing is fetched; following one moves to a record already in the page, and the
page's script opens it - clearing the filters first if they were hiding it.
"""

import html
from collections import defaultdict
from typing import Any

from .snapshot import Snapshot

OUT, IN = "out", "in"
ARROWS = {OUT: "→", IN: "←"}

# (relationship type, direction, kind of record it is shown on) -> heading. Where get_details has a heading for the
# same links, it is that heading.
HEADINGS: dict[tuple[str, str, str], str] = {
    ("implements", OUT, "requirement"): "Linked tasks",
    ("implements", IN, "task"): "Linked requirements",
    ("implements", OUT, "task"): "Implements decisions",
    ("implements", IN, "architecture"): "Implemented by",
    ("addresses", OUT, "requirement"): "Addresses decisions",
    ("addresses", IN, "architecture"): "Linked requirements",
    ("parent", OUT, "task"): "Parent task",
    ("parent", IN, "task"): "Subtasks",
    ("parent", OUT, "requirement"): "Parent requirements",
    ("parent", IN, "requirement"): "Child requirements",
    ("supersedes", OUT, "architecture"): "Supersedes",
    ("supersedes", IN, "architecture"): "Superseded by",
}

# Types whose meaning does not depend on the kind of record: dependent -> dependency, blocker -> blocked, and so on.
GENERIC: dict[tuple[str, str], str] = {
    ("depends", OUT): "Depends on",
    ("depends", IN): "Depended on by",
    ("requires", OUT): "Requires",
    ("requires", IN): "Required by",
    ("blocks", OUT): "Blocks",
    ("blocks", IN): "Blocked by",
    ("informs", OUT): "Informs",
    ("informs", IN): "Informed by",
    ("refines", OUT): "Refines",
    ("refines", IN): "Refined by",
    ("relates", OUT): "Relates to",
    ("relates", IN): "Related by",
    ("conflicts", OUT): "Conflicts with",
    ("conflicts", IN): "In conflict with",
}

LINKS_STYLE = """
a.id { text-decoration: none; }
a.id:hover, a.id:focus { text-decoration: underline; }
.links { margin: .875rem 0 0; }
.links h3 { font-size: .8125rem; font-weight: 600; margin: .625rem 0 .25rem; color: var(--muted); }
.links ul { list-style: none; margin: 0; padding: 0; display: grid; gap: .25rem; }
.links li { font-size: .875rem; }
.links .arrow { color: var(--muted); display: inline-block; width: 1.1em; }
.links .missing { color: var(--muted); font-style: italic; }
"""


def heading(relationship_type: str, direction: str, kind: str) -> str:
    """What to call one group of links on one kind of record."""
    return (
        HEADINGS.get((relationship_type, direction, kind))
        or GENERIC.get((relationship_type, direction))
        or f"{relationship_type.capitalize()} {ARROWS[direction]}"
    )


def link_index(snapshot: Snapshot) -> dict[str, list[tuple[str, str, str]]]:
    """Every record's links from its own end: id -> [(relationship type, direction, the other record's id)]."""
    index: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for link in snapshot.relationships:
        source, target, kind = str(link["source_id"]), str(link["target_id"]), str(link["relationship_type"])
        index[source].append((kind, OUT, target))
        index[target].append((kind, IN, source))
    return index


def record_titles(snapshot: Snapshot) -> dict[str, dict[str, Any]]:
    """Each record's title and status by id, for naming the record at the other end of a link."""
    return {
        str(row["id"]): {"title": row.get("title"), "status": row.get("status")}
        for rows in (snapshot.requirements, snapshot.tasks, snapshot.architecture)
        for row in rows
    }


def anchor(record_id: str, known: dict[str, dict[str, Any]]) -> str:
    """A link to a record in the page, or its id as plain text if the page does not hold it."""
    escaped = html.escape(record_id, quote=True)
    if record_id in known:
        return f'<a class="id" href="#{escaped}">{escaped}</a>'
    return f'<span class="id">{escaped}</span> <span class="missing">not in this tracker</span>'


def links_html(
    record_id: str, kind: str, index: dict[str, list[tuple[str, str, str]]], known: dict[str, dict[str, Any]]
) -> str:
    """The record's links, grouped by type and direction; "" when it has none, so no empty section appears."""
    links = index.get(record_id)
    if not links:
        return ""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for relationship_type, direction, other in links:
        groups[(relationship_type, direction)].append(other)

    sections = []
    for (relationship_type, direction), others in sorted(groups.items()):
        items = "".join(
            f'<li><span class="arrow">{ARROWS[direction]}</span>{anchor(other, known)} '
            f"{html.escape(str(known.get(other, {}).get('title') or ''))}"
            + (
                f' <span class="pill">{html.escape(str(known[other]["status"]))}</span>'
                if known.get(other, {}).get("status")
                else ""
            )
            + "</li>"
            for other in sorted(set(others))
        )
        label = heading(relationship_type, direction, kind)
        sections.append(
            f'<h3 data-type="{html.escape(relationship_type)}" data-direction="{direction}">'
            f"{html.escape(label)} ({len(set(others))})</h3><ul>{items}</ul>"
        )
    return f'<div class="links">{"".join(sections)}</div>'
