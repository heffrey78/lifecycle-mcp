"""The command that writes the viewer, and the documentation that tells people it exists (TASK-0095).

scripts/tracker_viewer.py is a script rather than a package module, so it is loaded from its path the way
test_r18_acceptance loads tool_usage_report. The make target itself is not run here - tests/conftest.py fails any test
that spawns git, and the target is a one-line wrapper - so its recipe is read instead, and the script it calls is
exercised directly.
"""

import importlib.util
import re
import sys
from pathlib import Path

from .test_tool_results import mcp_server, populate  # noqa: F401 (mcp_server is a fixture)
from .test_viewer_snapshot import db_path

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("tracker_viewer", ROOT / "scripts" / "tracker_viewer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the script ----------------------------------------------------------------------------------


def test_loading_the_script_prints_nothing(capsys):
    """Stdout is the protocol channel anywhere this could be imported; only main() may print."""
    load_script()

    assert capsys.readouterr().out == ""


async def test_it_writes_the_page_where_it_is_told_and_says_so(mcp_server, tmp_path, capsys):  # noqa: F811
    await populate(mcp_server)
    script = load_script()
    destination = tmp_path / "view.html"

    status = script.main(["--db", str(db_path(mcp_server)), "--out", str(destination)])

    assert status == 0
    assert destination.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    out = capsys.readouterr().out
    assert str(destination) in out and "1 requirements" in out and "run again to refresh" in out


async def test_generate_is_importable_and_silent(mcp_server, tmp_path, capsys):  # noqa: F811
    await populate(mcp_server)

    written, snapshot = load_script().generate(db_path(mcp_server), tmp_path / "view.html")

    assert written.exists() and snapshot.counts()["requirements"] == 1
    assert capsys.readouterr().out == ""


def test_the_default_output_is_named_for_the_project(tmp_path):
    script = load_script()

    output = script.default_output(tmp_path / "quire" / "lifecycle.db")

    assert output == script.EXPORTS / "quire-tracker.html", "two projects' viewers do not overwrite each other"
    assert script.EXPORTS == ROOT / "exports"


def test_the_default_tracker_is_this_repositorys_whatever_lifecycle_db_says(monkeypatch):
    """LIFECYCLE_DB aimed at another project is routine when the tracker is dogfooded on several at once."""
    monkeypatch.setenv("LIFECYCLE_DB", "/somewhere/else/lifecycle.db")

    args = load_script().parse_args([])

    assert args.db == ROOT / "lifecycle.db"


def test_a_missing_tracker_is_reported_and_never_created(tmp_path, capsys):
    """DatabaseManager would have built a fresh tracker here and the page would show an empty project."""
    missing = tmp_path / "typo" / "lifecycle.db"

    status = load_script().main(["--db", str(missing), "--out", str(tmp_path / "view.html")])

    assert status == 1
    assert str(missing) in capsys.readouterr().err
    assert not missing.exists() and not (tmp_path / "view.html").exists()


async def test_another_projects_tracker_is_one_argument_away(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)
    elsewhere = tmp_path / "quire" / "lifecycle.db"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(db_path(mcp_server).read_bytes())

    written, _ = load_script().generate(elsewhere, tmp_path / "quire.html")

    assert "<title>quire tracker</title>" in written.read_text(encoding="utf-8")


# --- make and git --------------------------------------------------------------------------------


def test_make_viewer_calls_the_script_and_passes_db_and_out_through():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    recipe = re.search(r"^viewer:\n\t(.+)$", makefile, re.MULTILINE)
    assert recipe, "a viewer target"
    assert "scripts/tracker_viewer.py" in recipe.group(1)
    assert "--db" in recipe.group(1) and "$(DB)" in recipe.group(1)
    assert "--out" in recipe.group(1) and "$(OUT)" in recipe.group(1)
    assert re.search(r"^\.PHONY:.*\bviewer\b", makefile, re.MULTILINE)
    assert "make viewer" in makefile, "and help mentions it"


def test_the_output_directory_is_ignored_by_git():
    """Read rather than asked: tests/conftest.py fails any test that spawns git."""
    ignored = [line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]

    assert "exports/" in ignored


# --- documentation -------------------------------------------------------------------------------


def test_the_readme_says_what_the_file_is_how_to_refresh_it_and_that_it_is_sensitive():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Viewing the Tracker", 1)[1].split("\n## ", 1)[0]

    assert "make viewer" in section and "DB=" in section
    assert "snapshot, not a live view" in section
    assert "read-only" in section.lower()
    assert "plaintext" in section and "sensitive" in section
    assert "LIFECYCLE_DB" in section and "exports/" in section


def test_claude_md_carries_the_rule_that_is_easy_to_break():
    guidance = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "make viewer" in guidance
    assert "ReadOnlyDatabase" in guidance and "DatabaseManager" in guidance


def test_the_script_runs_as_a_program(tmp_path):
    """The same entry point make uses, as a process: exits 1 with a message on stderr for a missing tracker."""
    import subprocess

    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "tracker_viewer.py"), "--db", str(tmp_path / "none.db")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 1
    assert "none.db" in completed.stderr and completed.stdout == ""
