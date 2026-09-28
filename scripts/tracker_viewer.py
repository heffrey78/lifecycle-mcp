#!/usr/bin/env python3
"""Generate a read-only HTML view of a lifecycle tracker (REQ-0006-INTF-00, TASK-0095).

    make viewer                                   # this repository's tracker
    make viewer DB=~/work/quire/lifecycle.db      # another project's
    uv run python scripts/tracker_viewer.py --db PATH --out PATH

The result is one HTML file that opens by double-clicking, with nothing installed and nothing fetched. It is a snapshot
of the moment it was generated: run this again to see later changes.

It reads this repository's lifecycle.db by default, and deliberately not whatever LIFECYCLE_DB points at. The tracker is
dogfooded on several projects at once, so LIFECYCLE_DB aimed elsewhere is routine rather than a mistake, and a command
that says it shows this repository must not quietly show another. Another project's tracker is one argument away.

The database is opened read-only. A path that does not exist is reported, never created: the server's DatabaseManager
would build a fresh tracker at a mistyped path and the page would render it as an empty project.

The page embeds the whole tracker as plaintext, so it is exactly as sensitive as the database it came from.
"""

import argparse
import sys
from pathlib import Path

from lifecycle_mcp.viewer.figures import derive_figures
from lifecycle_mcp.viewer.render import project_name, write_page
from lifecycle_mcp.viewer.snapshot import ReadOnlyDatabase, Snapshot, read_snapshot

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO / "lifecycle.db"
EXPORTS = REPO / "exports"


def default_output(db_path: Path) -> Path:
    """exports/<project>-tracker.html, so viewers of different projects do not overwrite each other."""
    return EXPORTS / f"{project_name(str(db_path.resolve()))}-tracker.html"


def generate(db_path: Path, output_path: Path | None = None) -> tuple[Path, Snapshot]:
    """Write the page for one tracker; return where it landed and what it held.

    Prints nothing, so importing or calling this never writes to stdout. Raises FileNotFoundError if the tracker is
    absent rather than creating one.
    """
    snapshot = read_snapshot(db_path)
    figures = derive_figures(snapshot, ReadOnlyDatabase(db_path))
    return write_page(snapshot, figures, output_path or default_output(db_path)), snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a read-only HTML view of a lifecycle tracker.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"the tracker to view (default: this repository's, {DEFAULT_DB.name}; LIFECYCLE_DB is not consulted)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="where to write it (default: exports/<project>-tracker.html)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        written, snapshot = generate(args.db, args.out)
    except FileNotFoundError as error:
        print(f"{error}. Nothing was created; pass --db with the tracker you meant.", file=sys.stderr)
        return 1
    counts = snapshot.counts()
    size = written.stat().st_size / 1024
    print(
        f"Wrote {written} ({size:.0f} KB): {counts['requirements']} requirements, {counts['tasks']} tasks, "
        f"{counts['architecture']} decisions. A snapshot of now; run again to refresh it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
