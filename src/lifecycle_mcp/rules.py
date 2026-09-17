#!/usr/bin/env python3
"""Workflow rules: how strictly the server treats risky status moves, and the thresholds they read (roadmap R8,
ADR-0004).

LIFECYCLE_RULES picks the mode. In warn, the default, every call keeps the outcome it has today and a risky move
only gains an explanation. In enforce the move is refused. In off nothing is checked.

The rules that protect what the server maintains itself -- the Validated gate, the Superseded link and the
requirement transition map -- are always on and live with their handlers, not here.
"""

import logging
import os

logger = logging.getLogger(__name__)

RULES_ENV_FLAG = "LIFECYCLE_RULES"
OFF, WARN, ENFORCE = "off", "warn", "enforce"
MODES = (OFF, WARN, ENFORCE)

# How long a requirement may go unchecked before the dashboard chases it, in days. Creation counts as the first
# check, so this is the age at which a requirement nobody has looked at since is worth re-reading, not a signal
# that fires the moment a record is written (roadmap R17, F-43). 0 chases every requirement immediately.
STALE_AFTER_ENV_FLAG = "LIFECYCLE_STALE_AFTER"
STALE_AFTER_DEFAULT_DAYS = 14.0


# Fields a new record usually needs, by kind. Measured in this project's own tracker on 2026-09-16: the curated
# fields R6b made reachable were mostly empty (validation_metrics 0/18 requirements, test_plan 12/69 tasks), and
# validation_metrics is where a measurable target like "p95 under 50 ms" belongs (roadmap R11).
THIN_REQUIREMENT_FIELDS = {
    "acceptance_criteria": ("every requirement", None),
    "validation_metrics": ("an NFUNC requirement", "NFUNC"),
}
THIN_TASK_PRIORITIES = ("P0", "P1")


def thin_record_reasons(params: dict, kind: str) -> list[str]:
    """Why a new record is thin for its kind, for the workflow rules to warn about or refuse (roadmap R11)."""
    reasons = []
    if kind == "requirement":
        for field, (describes, only_type) in THIN_REQUIREMENT_FIELDS.items():
            if only_type and params.get("type") != only_type:
                continue
            if not params.get(field):
                reasons.append(f"No {field}: {describes} needs one to be checkable later")
    elif kind == "task" and params.get("priority") in THIN_TASK_PRIORITIES and not params.get("test_plan"):
        reasons.append(f"No test_plan: a {params['priority']} task needs one to show when it is done")
    return reasons


def stale_after_days() -> float:
    """Days a requirement may go unchecked before it is chased; LIFECYCLE_STALE_AFTER overrides the default."""
    value = os.environ.get(STALE_AFTER_ENV_FLAG, "").strip()
    if not value:
        return STALE_AFTER_DEFAULT_DAYS
    try:
        days = float(value)
    except ValueError:
        days = -1.0
    if days < 0:
        logger.warning(f"{STALE_AFTER_ENV_FLAG}={value!r} is not a number of days; using {STALE_AFTER_DEFAULT_DAYS}")
        return STALE_AFTER_DEFAULT_DAYS
    return days


def rules_mode() -> str:
    """off, warn or enforce; warn unless LIFECYCLE_RULES says otherwise."""
    value = os.environ.get(RULES_ENV_FLAG, "").strip().lower()
    if not value:
        return WARN
    if value in MODES:
        return value
    logger.warning(f"{RULES_ENV_FLAG}={value!r} is not one of {', '.join(MODES)}; using {WARN}")
    return WARN
