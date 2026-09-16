#!/usr/bin/env python3
"""Workflow rules: how strictly the server treats risky status moves (roadmap R8, ADR-0004).

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


def rules_mode() -> str:
    """off, warn or enforce; warn unless LIFECYCLE_RULES says otherwise."""
    value = os.environ.get(RULES_ENV_FLAG, "").strip().lower()
    if not value:
        return WARN
    if value in MODES:
        return value
    logger.warning(f"{RULES_ENV_FLAG}={value!r} is not one of {', '.join(MODES)}; using {WARN}")
    return WARN
