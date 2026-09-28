#!/usr/bin/env python3
"""The tracker as text in the repository, and a tracker rebuilt from it (REQ-0007-TECH-00).

    make tracker-export                      # lifecycle.db -> lifecycle-data.sql
    make tracker-restore                     # lifecycle-data.sql -> lifecycle.db, refusing to overwrite records
    uv run python scripts/tracker_dump.py restore --into /tmp/check.db   # rebuild somewhere to inspect it
    uv run python scripts/tracker_dump.py restore --force                # replace a tracker that holds records

Both halves use this repository's files by default and never the database LIFECYCLE_DB names: the tracker is dogfooded
on several projects at once, so LIFECYCLE_DB routinely points elsewhere, and a dump of this repository must not be
filled from another project, nor another project's tracker overwritten by this one's dump.

Stop the server before restoring over a tracker it has open. The replaced file is swapped out from under it, and until
it reconnects it keeps writing to the old one.
"""

import argparse
import sys
from pathlib import Path

from lifecycle_mcp.dump import RestoreRefused, restore, write_dump

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "lifecycle.db"
DEFAULT_DUMP = REPO / "lifecycle-data.sql"


def _describe(counts: dict[str, int]) -> str:
    return ", ".join(f"{count} {table}" for table, count in counts.items()) or "no records"


def run_export(db: Path, out: Path) -> int:
    if not db.exists():
        print(f"No tracker at {db}; nothing to export.", file=sys.stderr)
        return 0
    changed = write_dump(db, out)
    print(f"Wrote {out}." if changed else f"{out} is already current.")
    return 0


def run_restore(dump: Path, into: Path, force: bool) -> int:
    if not dump.exists():
        print(f"No dump at {dump}.", file=sys.stderr)
        return 1
    try:
        result = restore(dump.read_text(encoding="utf-8"), into, force=force)
    except RestoreRefused as refusal:
        print(f"Refused: {refusal}", file=sys.stderr)
        return 1
    print(
        f"Rebuilt {result['target']} from {dump.name}: {_describe(result['restored'])}. "
        f"Schema version {result['dump_version']} -> {result['version']}."
    )
    if result["replaced"]:
        print(f"Replaced a tracker that held {_describe(result['replaced'])}.")
    if result["had_write_ahead_log"]:
        print(
            "The replaced tracker had a write-ahead log, which usually means a server had it open. Restart the "
            "server now: until it reconnects it keeps writing to the file that was replaced.",
            file=sys.stderr,
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the tracker as SQL text, or rebuild a tracker from it.")
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export", help="write the tracker's rows to the dump")
    export.add_argument("--db", type=Path, default=DEFAULT_DB, help="the tracker (default: this repository's)")
    export.add_argument("--out", type=Path, default=DEFAULT_DUMP, help=f"the dump (default: {DEFAULT_DUMP.name})")

    rebuild = commands.add_parser("restore", help="rebuild a tracker from the dump")
    rebuild.add_argument("--from", dest="dump", type=Path, default=DEFAULT_DUMP, help="the dump to read")
    rebuild.add_argument("--into", type=Path, default=DEFAULT_DB, help="where to build (default: this repository's)")
    rebuild.add_argument("--force", action="store_true", help="replace a tracker that already holds records")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "export":
        return run_export(args.db, args.out)
    return run_restore(args.dump, args.into, args.force)


if __name__ == "__main__":
    sys.exit(main())
