"""The dump's command line and the commit hook that runs it (REQ-0007-TECH-00, TASK-0103).

tests/conftest.py fails any test that spawns git, so staging is exercised through run_export's `add` parameter: the
tests hand it a recorder and check exactly what would have been staged, and when. The hook's configuration is read as
text, since the pre-commit framework cannot be run here either.
"""

import importlib.util
import re
from pathlib import Path

from lifecycle_mcp.dump import export_rows

from .test_tool_results import call, mcp_server, populate  # noqa: F401 (mcp_server is a fixture)
from .test_viewer_snapshot import db_path

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("tracker_dump", ROOT / "scripts" / "tracker_dump.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hook_block(config: str, hook_id: str) -> str:
    match = re.search(rf"- id: {re.escape(hook_id)}\n((?:\s{{8,}}.*\n)*)", config)
    assert match, f"{hook_id} hook"
    return match.group(0)


# --- the hook's export step ----------------------------------------------------------------------


async def test_a_changed_tracker_is_written_and_exactly_that_file_staged(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)
    staged: list[Path] = []
    out = tmp_path / "lifecycle-data.sql"

    status = load_script().run_export(db_path(mcp_server), out, stage=True, add=staged.append)

    assert status == 0 and staged == [out]
    assert out.read_text(encoding="utf-8") == export_rows(db_path(mcp_server))


async def test_an_unchanged_tracker_writes_nothing_and_stages_nothing(mcp_server, tmp_path, capsys):  # noqa: F811
    """A commit that touched only code carries no dump diff."""
    await populate(mcp_server)
    script = load_script()
    out = tmp_path / "lifecycle-data.sql"
    script.run_export(db_path(mcp_server), out, stage=True, add=lambda path: None)
    capsys.readouterr()
    staged: list[Path] = []

    script.run_export(db_path(mcp_server), out, stage=True, add=staged.append)

    assert staged == []
    assert "already current" in capsys.readouterr().out


async def test_a_new_record_is_staged_on_the_next_commit(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    script = load_script()
    out = tmp_path / "lifecycle-data.sql"
    script.run_export(db_path(mcp_server), out, stage=True, add=lambda path: None)
    assert not (await call(mcp_server, "add_comment", {"entity_id": ids["task"], "comment": "picked up"})).isError
    staged: list[Path] = []

    script.run_export(db_path(mcp_server), out, stage=True, add=staged.append)

    assert staged == [out] and "picked up" in out.read_text(encoding="utf-8")


def test_a_clone_with_no_tracker_commits_normally(tmp_path, capsys):
    staged: list[Path] = []

    status = load_script().run_export(tmp_path / "lifecycle.db", tmp_path / "out.sql", stage=True, add=staged.append)

    assert status == 0 and staged == []
    assert "nothing to export" in capsys.readouterr().err
    assert not (tmp_path / "out.sql").exists() and not (tmp_path / "lifecycle.db").exists()


def test_the_hook_exports_this_repositorys_tracker_whatever_lifecycle_db_says(monkeypatch):
    """LIFECYCLE_DB aimed at a work project is routine; its tracker must never land in this repository's dump."""
    monkeypatch.setenv("LIFECYCLE_DB", "/work/other-project/lifecycle.db")

    args = load_script().parse_args(["export", "--stage"])

    assert args.db == ROOT / "lifecycle.db" and args.out == ROOT / "lifecycle-data.sql"


def test_loading_the_script_prints_nothing(capsys):
    load_script()

    assert capsys.readouterr().out == ""


# --- the hook's configuration --------------------------------------------------------------------


def test_the_hook_runs_the_export_on_every_commit():
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    hook = hook_block(config, "tracker-dump")

    assert "scripts/tracker_dump.py export --stage" in hook
    assert "always_run: true" in hook, "the tracker changes without any tracked file changing"
    assert "pass_filenames: false" in hook
    assert "language: system" in hook


def test_no_fixer_or_size_limit_touches_the_dump():
    """A fixer rewriting whitespace inside the dump would change tracker data; the size limit is for stray binaries."""
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    for hook_id in ("trailing-whitespace", "end-of-file-fixer", "mixed-line-ending", "check-added-large-files"):
        assert r"exclude: ^lifecycle-data\.sql$" in hook_block(config, hook_id), hook_id


def test_github_shows_the_dump_as_generated():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert re.search(r"^lifecycle-data\.sql\s+linguist-generated=true$", attributes, re.MULTILINE)


# --- restore from the command line ---------------------------------------------------------------


async def test_restore_refuses_a_tracker_with_records_and_exits_nonzero(mcp_server, tmp_path, capsys):  # noqa: F811
    await populate(mcp_server)
    script = load_script()
    dump = tmp_path / "lifecycle-data.sql"
    script.run_export(db_path(mcp_server), dump)

    status = script.main(["restore", "--from", str(dump), "--into", str(db_path(mcp_server))])

    assert status == 1
    assert "Refused" in capsys.readouterr().err


async def test_restore_into_a_new_path_says_what_it_built(mcp_server, tmp_path, capsys):  # noqa: F811
    await populate(mcp_server)
    script = load_script()
    dump = tmp_path / "lifecycle-data.sql"
    script.run_export(db_path(mcp_server), dump)
    capsys.readouterr()

    status = script.main(["restore", "--from", str(dump), "--into", str(tmp_path / "rebuilt.db")])

    out = capsys.readouterr().out
    assert status == 0 and "1 requirements" in out and "Schema version" in out
    assert export_rows(tmp_path / "rebuilt.db") == dump.read_text(encoding="utf-8")


def test_restore_from_a_missing_dump_exits_nonzero(tmp_path, capsys):
    status = load_script().main(["restore", "--from", str(tmp_path / "none.sql"), "--into", str(tmp_path / "x.db")])

    assert status == 1 and "none.sql" in capsys.readouterr().err
    assert not (tmp_path / "x.db").exists()


# --- make, documentation, and the committed dump (TASK-0104) -------------------------------------


def test_the_make_targets_run_both_halves_and_pass_arguments_through():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    export = re.search(r"^tracker-export:\n\t(.+)$", makefile, re.MULTILINE)
    rebuild = re.search(r"^tracker-restore:\n\t(.+)$", makefile, re.MULTILINE)
    assert export and "scripts/tracker_dump.py export" in export.group(1)
    assert rebuild and "scripts/tracker_dump.py restore" in rebuild.group(1)
    assert '$(if $(INTO),--into "$(INTO)")' in rebuild.group(1) and "$(if $(FORCE),--force)" in rebuild.group(1)
    assert re.search(r"^\.PHONY:.*\btracker-export\b.*\btracker-restore\b", makefile, re.MULTILINE)


def test_the_readme_says_what_the_dump_is_and_how_to_rebuild_from_it():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## The Tracker in Git", 1)[1].split("\n## ", 1)[0]

    for needed in (
        "lifecycle-data.sql",
        "Never edit it by hand",
        "make tracker-restore",
        "Stop the server before replacing",
        "FORCE=1",
        "LIFECYCLE_DB",
        "pre-commit install",
    ):
        assert needed in section, needed


def test_claude_md_carries_the_dumps_rules():
    guidance = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert "make tracker-export" in guidance and "make tracker-restore" in guidance
    assert "never the dump" in guidance, "the schema lives in migrations"
    assert "updated_at" in guidance, "and why records load last"


def test_the_committed_dump_rebuilds_a_tracker(tmp_path):
    """CI cannot see the tracker - it is local by design - but it can see its dump. A dump that was hand-edited, cut
    short or corrupted fails here, in the build, rather than in someone's restore."""
    from lifecycle_mcp.dump import parse_dump, restore

    committed = ROOT / "lifecycle-data.sql"
    if not committed.exists():
        return  # a fork without a tracker has no dump to check
    text = committed.read_text(encoding="utf-8")

    result = restore(text, tmp_path / "rebuilt.db")

    parsed = parse_dump(text)
    assert result["restored"] == {t: n for t, n in parsed.counts().items() if t != "schema_version" and n}
    assert result["restored"].get("requirements"), "a tracker with requirements in it"
