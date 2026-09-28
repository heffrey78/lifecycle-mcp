"""The dashboard's figures, computed once by the generator (REQ-0006-INTF-00, TASK-0091).

Every figure here comes from the definition that already computes it for the tools: WORK_COMPLETE_WHERE,
BLOCKED_TASKS_SQL, READY_TASKS_WHERE, and the verification derivation behind staleness and changed-since-review. They
are imported and run, not reproduced, because a viewer with its own copy of "work complete" would eventually disagree
with the dashboard about the same requirement, and the reader would have no way to tell which was right.

That is also why this is computed here rather than in the page. Nothing in the rendered file performs a lifecycle
judgement; it filters and presents what these functions decided.
"""

from dataclasses import dataclass, field
from typing import Any

from ..handlers.requirement_handler import (
    WORK_COMPLETE_WHERE,
    changes_since_review,
    describe_age,
    stale_requirements,
)
from ..handlers.status_handler import BLOCKED_TASKS_SQL
from ..handlers.task_handler import READY_TASKS_ORDER, READY_TASKS_WHERE
from .snapshot import ReadOnlyDatabase, Snapshot

WORK_COMPLETE_SQL = (
    f"SELECT id, title, status, priority, task_count FROM requirements "
    f"WHERE {WORK_COMPLETE_WHERE} ORDER BY priority, id"
)
READY_TASKS_SQL = (
    f"SELECT t.id, t.title, t.status, t.priority, t.effort FROM tasks t "
    f"WHERE {READY_TASKS_WHERE} ORDER BY {READY_TASKS_ORDER}"
)


@dataclass
class Figures:
    """What the dashboard's sections say, decided before the page is written."""

    blocked: list[dict[str, Any]] = field(default_factory=list)
    work_complete: list[dict[str, Any]] = field(default_factory=list)
    changed_since_review: list[dict[str, Any]] = field(default_factory=list)
    stale: list[dict[str, Any]] = field(default_factory=list)
    ready: list[dict[str, Any]] = field(default_factory=list)
    requirements_by_status: dict[str, int] = field(default_factory=dict)
    requirements_by_priority: dict[str, int] = field(default_factory=dict)
    tasks_by_status: dict[str, int] = field(default_factory=dict)
    tasks_by_priority: dict[str, int] = field(default_factory=dict)
    architecture_by_status: dict[str, int] = field(default_factory=dict)
    # Why a section is empty, so an empty one says which case it is rather than nothing at all (roadmap R17).
    empty_reasons: dict[str, str] = field(default_factory=dict)

    def section_counts(self) -> dict[str, int]:
        return {
            "blocked": len(self.blocked),
            "work_complete": len(self.work_complete),
            "changed_since_review": len(self.changed_since_review),
            "stale": len(self.stale),
            "ready": len(self.ready),
        }


def _tally(rows: list[dict[str, Any]], column: str) -> dict[str, int]:
    """Counts by one column, from the snapshot rather than a second query over the same rows."""
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(column) or "Unassigned"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _blocked_rows(db: ReadOnlyDatabase) -> list[dict[str, Any]]:
    """Blocked and waiting tasks, from the dashboard's own query."""
    rows = db.execute_query(BLOCKED_TASKS_SQL, [], fetch_all=True, row_factory=True) or []
    blocked = []
    for row in rows:
        entry = dict(row)
        entry["waiting_on"] = [item for item in (row["waiting_on"] or "").split(", ") if item]
        entry["abandoned"] = [item for item in (row["abandoned"] or "").split(", ") if item]
        blocked.append(entry)
    return blocked


def _why_nothing_ready(snapshot: Snapshot) -> str:
    """Which of the three cases an empty ready list is: no work left, all waiting, or already under way.

    The three cases are the ones _nothing_ready reports for query_tasks. The counts come from the snapshot; the
    wording is the page's, because a message is presentation and only the figures have to be the server's.
    """
    in_progress = sum(1 for task in snapshot.tasks if task["status"] == "In Progress")
    blocked = sum(1 for task in snapshot.tasks if task["status"] == "Blocked")
    open_tasks = sum(1 for task in snapshot.tasks if task["status"] not in ("Complete", "Abandoned"))
    if not snapshot.tasks:
        return "No tasks exist yet."
    if not open_tasks:
        return "No tasks remain: every task is Complete or Abandoned."
    parts = []
    if in_progress:
        parts.append(f"{in_progress} already under way")
    if blocked:
        parts.append(f"{blocked} Blocked")
    waiting = open_tasks - in_progress - blocked
    if waiting:
        parts.append(f"{waiting} waiting on a dependency")
    return "Nothing is ready to start: " + ", ".join(parts) + "."


def _empty_reasons(snapshot: Snapshot, figures: Figures) -> dict[str, str]:
    """A sentence for each empty section, so silence is never ambiguous (roadmap R17)."""
    reasons = {}
    if not figures.ready:
        reasons["ready"] = _why_nothing_ready(snapshot)
    if not figures.blocked:
        reasons["blocked"] = "Nothing is blocked and nothing is waiting on an unfinished dependency."
    if not figures.work_complete:
        reasons["work_complete"] = (
            "No requirement has its work finished and its decision outstanding."
            if snapshot.requirements
            else "No requirements exist yet."
        )
    if not figures.changed_since_review:
        reasons["changed_since_review"] = "No reviewed requirement has been edited since its last status change."
    if not figures.stale:
        reasons["stale"] = "Every requirement has been checked since it last changed."
    return reasons


def derive_figures(snapshot: Snapshot, db: ReadOnlyDatabase | None = None) -> Figures:
    """Run the server's own definitions against the tracker the snapshot came from."""
    db = db or ReadOnlyDatabase(snapshot.database_path)

    stale = []
    for requirement_id, entry in stale_requirements(db).items():
        stale.append(
            {
                "id": requirement_id,
                "title": entry["title"],
                "status": entry["status"],
                "verified_at": entry["verified_at"],
                "changed_at": entry["changed_at"],
                "stale_reason": entry["stale_reason"],
                # The same phrasing the dashboard uses, from the same function.
                "age": describe_age(entry["age_days"]),
            }
        )

    changed = [{"id": requirement_id, **entry} for requirement_id, entry in sorted(changes_since_review(db).items())]

    figures = Figures(
        blocked=_blocked_rows(db),
        work_complete=[
            dict(row) for row in db.execute_query(WORK_COMPLETE_SQL, [], fetch_all=True, row_factory=True) or []
        ],
        changed_since_review=changed,
        stale=stale,
        ready=[dict(row) for row in db.execute_query(READY_TASKS_SQL, [], fetch_all=True, row_factory=True) or []],
        requirements_by_status=_tally(snapshot.requirements, "status"),
        requirements_by_priority=_tally(snapshot.requirements, "priority"),
        tasks_by_status=_tally(snapshot.tasks, "status"),
        tasks_by_priority=_tally(snapshot.tasks, "priority"),
        architecture_by_status=_tally(snapshot.architecture, "status"),
    )
    figures.empty_reasons = _empty_reasons(snapshot, figures)
    return figures
