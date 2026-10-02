"""The tracker as deterministic SQL text, and a tracker rebuilt from it (REQ-0007-TECH-00).

Structure is asserted rather than substrings. The first run of this export against the repository's own tracker
"found" CREATE and TRIGGER in it - inside records that discuss CREATE statements and triggers. What matters is that
every statement is an INSERT, and that is what these tests read.
"""

import os
import sqlite3
from pathlib import Path

import pytest

from lifecycle_mcp.dump import data_tables, export_rows, sql_literal, write_dump

from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)
from .test_viewer_snapshot import db_path, file_bytes

TRICKY = 'It\'s "quoted",\nsplit across lines,\r\nwith a tab\there, trailing space \nand ünïcødé ✓'


def statements(dump: str) -> list[str]:
    return [line for line in dump.splitlines() if line and not line.startswith("--")]


def load_into_copy_of_schema(source: Path, dump: str) -> sqlite3.Connection:
    """A fresh database with the source's tables, loaded from the dump."""
    original = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        ddl = [
            row[0]
            for row in original.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
    finally:
        original.close()
    copy = sqlite3.connect(":memory:")
    for statement in ddl:
        copy.execute(statement)
    copy.executescript(dump)
    return copy


def rows(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return connection.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()  # noqa: S608


# --- export (TASK-0101) --------------------------------------------------------------------------


async def test_two_exports_of_an_unchanged_tracker_are_identical(mcp_server):  # noqa: F811
    await populate(mcp_server)
    path = db_path(mcp_server)

    assert export_rows(path) == export_rows(path)


async def test_every_statement_is_an_insert_into_a_table_the_database_has(mcp_server):  # noqa: F811
    await populate(mcp_server)
    path = db_path(mcp_server)
    connection = sqlite3.connect(str(path))
    try:
        tables = set(data_tables(connection))
    finally:
        connection.close()

    found = statements(export_rows(path))

    assert found
    for statement in found:
        assert statement.startswith('INSERT INTO "') and statement.endswith(");"), statement[:80]
        assert statement.split('"')[1] in tables, statement[:80]


async def test_each_row_is_one_line_whatever_its_text_holds(mcp_server):  # noqa: F811
    """This repository's pre-commit config strips trailing whitespace and normalises line endings. A value spanning
    lines would be rewritten by them; spliced with char(10), there is nothing for them to touch."""
    ids = await populate(mcp_server)
    assert not (await call(mcp_server, "add_comment", {"entity_id": ids["requirement"], "comment": TRICKY})).isError

    dump = export_rows(db_path(mcp_server))

    assert "\r" not in dump
    assert all(line.startswith(("INSERT INTO", "--")) for line in dump.splitlines() if line)
    assert "char(10)" in dump and "char(13)" in dump
    assert not any(line != line.rstrip() for line in dump.splitlines()), (
        "no line ends in whitespace a fixer would strip"
    )


async def test_every_value_survives_the_round_trip(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    assert not (await call(mcp_server, "add_comment", {"entity_id": ids["requirement"], "comment": TRICKY})).isError
    path = db_path(mcp_server)
    source = sqlite3.connect(str(path))

    copy = load_into_copy_of_schema(path, export_rows(path))

    try:
        for table in data_tables(source):
            assert rows(copy, table) == rows(source, table), table
        assert TRICKY in [row[0] for row in copy.execute("SELECT comment FROM reviews")]
    finally:
        source.close()
        copy.close()


async def test_a_table_a_future_migration_adds_is_exported_without_a_code_change(mcp_server):  # noqa: F811
    await populate(mcp_server)
    path = db_path(mcp_server)
    writer = sqlite3.connect(str(path))
    try:
        writer.execute("CREATE TABLE milestones (id TEXT PRIMARY KEY, title TEXT)")
        writer.execute("INSERT INTO milestones VALUES ('M-1', 'First release')")
        writer.commit()
    finally:
        writer.close()

    dump = export_rows(path)

    assert """INSERT INTO "milestones" ("id", "title") VALUES ('M-1', 'First release');""" in dump


async def test_exporting_reads_the_wal_and_writes_nothing(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    path = db_path(mcp_server)
    before = file_bytes(path)

    dump = export_rows(path)

    assert file_bytes(path) == before, "the database and its -wal are untouched"
    assert ids["requirement"] in dump, "and what the server has written is in it"


async def test_the_export_does_not_depend_on_where_the_database_is(mcp_server, tmp_path):  # noqa: F811
    """No path, time or host in the file: the same tracker gives the same text on any machine."""
    await populate(mcp_server)
    path = db_path(mcp_server)
    elsewhere = tmp_path / "somewhere" / "else.db"
    elsewhere.parent.mkdir()
    source = sqlite3.connect(str(path))
    try:
        source.execute(f"VACUUM INTO '{elsewhere}'")
    finally:
        source.close()

    assert export_rows(elsewhere) == export_rows(path)


async def test_writing_leaves_an_unchanged_dump_untouched(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    path = db_path(mcp_server)
    out = tmp_path / "lifecycle-data.sql"

    assert write_dump(path, out) is True
    stamp = out.stat().st_mtime_ns
    os.utime(out, ns=(stamp - 10_000_000_000, stamp - 10_000_000_000))
    assert write_dump(path, out) is False, "unchanged tracker, unchanged file"
    assert out.stat().st_mtime_ns == stamp - 10_000_000_000, "not even rewritten with the same bytes"

    assert not (await call(mcp_server, "add_comment", {"entity_id": ids["task"], "comment": "moved on"})).isError
    assert write_dump(path, out) is True


def test_a_missing_tracker_is_named_and_not_created(tmp_path):
    missing = tmp_path / "typo" / "lifecycle.db"

    with pytest.raises(FileNotFoundError, match="typo"):
        export_rows(missing)
    assert not missing.exists() and not missing.parent.exists()


@pytest.mark.parametrize(
    ("value", "literal"),
    [
        (None, "NULL"),
        (True, "1"),
        (42, "42"),
        (1.5, "1.5"),
        (b"\x00\xff", "X'00ff'"),
        ("", "''"),
        ("it's", "'it''s'"),
        ("a\nb", "'a' || char(10) || 'b'"),
        ("\n", "char(10)"),
        ("end\r\n", "'end' || char(13) || char(10)"),
    ],
)
def test_values_are_written_as_sqlite_reads_them_back(value, literal):
    assert sql_literal(value) == literal
    if value is not None and not isinstance(value, bool):
        assert sqlite3.connect(":memory:").execute(f"SELECT {literal}").fetchone()[0] == value


def test_a_float_with_no_literal_is_refused():
    with pytest.raises(ValueError):
        sql_literal(float("nan"))


# --- restore (TASK-0102) -------------------------------------------------------------------------

from lifecycle_mcp.database_manager import create_baseline  # noqa: E402
from lifecycle_mcp.dump import RestoreRefused, latest_version, parse_dump, restore, tracker_rows  # noqa: E402
from lifecycle_mcp.migrations import apply_all_migrations  # noqa: E402


async def dumped(server) -> tuple[Path, str]:
    """A populated tracker with links, a comment and a multi-line value, and its dump."""
    ids = await populate(server)
    assert not (await call(server, "add_comment", {"entity_id": ids["requirement"], "comment": TRICKY})).isError
    path = db_path(server)
    return path, export_rows(path)


async def test_a_restored_tracker_exports_back_to_the_same_dump(mcp_server, tmp_path):  # noqa: F811
    _, dump = await dumped(mcp_server)
    target = tmp_path / "restored.db"

    result = restore(dump, target)

    assert export_rows(target) == dump
    assert result["restored"]["requirements"] == 1 and result["replaced"] == {}


async def test_restoring_leaves_every_records_timestamps_as_they_were(mcp_server, tmp_path):  # noqa: F811
    """Loading a relationship fires a trigger that updates requirements, which stamps updated_at with the current time.
    On this repository's tracker that marked 27 requirements edited at the moment of the restore."""
    path, _ = await dumped(mcp_server)
    writer = sqlite3.connect(str(path))
    try:
        # A timestamp far from now, set with the stamping trigger out of the way - through it, the trigger would
        # restamp the row to the current second, and a restore that did the same could not be told apart.
        trigger = writer.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'update_requirement_timestamp'"
        ).fetchone()[0]
        writer.execute("DROP TRIGGER update_requirement_timestamp")
        writer.execute("UPDATE requirements SET updated_at = '2020-01-01 00:00:00'")
        writer.execute(trigger)
        writer.commit()
    finally:
        writer.close()
    dump = export_rows(path)
    assert "'2020-01-01 00:00:00'" in dump
    target = tmp_path / "restored.db"

    restore(dump, target)

    rebuilt = sqlite3.connect(str(target))
    try:
        assert {row[0] for row in rebuilt.execute("SELECT updated_at FROM requirements")} == {"2020-01-01 00:00:00"}
    finally:
        rebuilt.close()


async def test_a_tracker_that_already_holds_records_is_not_replaced_without_force(mcp_server, tmp_path):  # noqa: F811
    path, dump = await dumped(mcp_server)
    before = file_bytes(path)

    with pytest.raises(RestoreRefused) as refusal:
        restore(dump, path)

    message = str(refusal.value)
    assert "1 requirements" in message and "--force" in message and "--into" in message
    assert file_bytes(path) == before, "nothing was written"


async def test_force_replaces_it_and_leaves_no_old_log_beside_the_new_file(mcp_server, tmp_path):  # noqa: F811
    """SQLite applies a -wal to whatever database sits beside it; the old one must not outlive its file."""
    path, dump = await dumped(mcp_server)
    target = tmp_path / "live.db"
    source = sqlite3.connect(str(path))
    try:
        source.execute(f"VACUUM INTO '{target}'")
    finally:
        source.close()
    holder = sqlite3.connect(str(target))
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("INSERT INTO reviews (entity_type, entity_id, reviewer, comment) VALUES ('task', 'T', 'x', 'old')")
    holder.commit()
    holder.close()

    result = restore(dump, target, force=True)

    assert result["replaced"]["reviews"] == 2, "it says what it replaced"
    assert not Path(f"{target}-wal").exists() or Path(f"{target}-wal").stat().st_size == 0
    assert export_rows(target) == dump, "and the new tracker is exactly the dump, with nothing from the old log"


async def test_into_builds_somewhere_else_and_leaves_the_tracker_alone(mcp_server, tmp_path):  # noqa: F811
    path, dump = await dumped(mcp_server)
    before = file_bytes(path)

    restore(dump, tmp_path / "copy.db")

    assert (tmp_path / "copy.db").exists() and file_bytes(path) == before


async def test_a_dump_newer_than_the_checkout_is_refused(mcp_server, tmp_path):  # noqa: F811
    _, dump = await dumped(mcp_server)
    future = latest_version() + 1
    newer = dump.replace(
        f'INSERT INTO "schema_version" ("version", "applied_at", "description") VALUES ({latest_version()},',
        f'INSERT INTO "schema_version" ("version", "applied_at", "description") VALUES ({future}, \'2030-01-01\', '
        f"'From the future');\n"
        f'INSERT INTO "schema_version" ("version", "applied_at", "description") VALUES ({latest_version()},',
    )
    target = tmp_path / "restored.db"

    with pytest.raises(RestoreRefused) as refusal:
        restore(newer, target)

    assert str(future) in str(refusal.value) and str(latest_version()) in str(refusal.value)
    assert not target.exists()


async def test_an_older_dump_is_carried_forward_by_the_migrations(tmp_path):
    """Build a tracker as it stood at version 17, before requirements had an origin, and restore its dump."""
    old = tmp_path / "old.db"
    create_baseline(old)
    apply_all_migrations(str(old), 17)
    writer = sqlite3.connect(str(old))
    try:
        writer.execute(
            "INSERT INTO requirements (id, requirement_number, type, version, title, status, priority, current_state, "
            "desired_state, author) VALUES ('REQ-0001-FUNC-00', 1, 'FUNC', 0, 'Old', 'Draft', 'P2', 'Then', 'Now', 'x')"
        )
        writer.commit()
    finally:
        writer.close()
    dump = export_rows(old)
    assert parse_dump(dump).version == 17 and '"origin"' not in dump
    target = tmp_path / "restored.db"

    result = restore(dump, target)

    assert result["dump_version"] == 17 and result["version"] == latest_version()
    rebuilt = sqlite3.connect(str(target))
    try:
        assert rebuilt.execute("SELECT origin FROM requirements").fetchone()[0] == "stated", "migration 18 ran over it"
        assert rebuilt.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == latest_version()
    finally:
        rebuilt.close()


@pytest.mark.parametrize(
    "smuggled",
    [
        "DELETE FROM requirements;",
        "CREATE TABLE extra (id TEXT);",
        "PRAGMA writable_schema = 1;",
        """INSERT INTO "reviews" ("id") VALUES (999); DROP TABLE requirements;""",
    ],
)
async def test_anything_but_an_insert_is_refused_before_a_row_is_written(mcp_server, tmp_path, smuggled):  # noqa: F811
    _, dump = await dumped(mcp_server)
    target = tmp_path / "restored.db"

    with pytest.raises(RestoreRefused):
        restore(dump + smuggled + "\n", target)

    assert not target.exists()
    assert not list(tmp_path.glob("*.restoring*")), "no half-built database is left behind"


async def test_a_row_that_fails_to_load_leaves_the_target_exactly_as_it_was(mcp_server, tmp_path):  # noqa: F811
    path, dump = await dumped(mcp_server)
    target = tmp_path / "live.db"
    source = sqlite3.connect(str(path))
    try:
        source.execute(f"VACUUM INTO '{target}'")
    finally:
        source.close()
    before = file_bytes(target)
    broken = dump + 'INSERT INTO "no_such_table" ("id") VALUES (1);\n'

    with pytest.raises(RestoreRefused, match="no_such_table"):
        restore(broken, target, force=True)

    assert file_bytes(target) == before
    assert not list(tmp_path.glob("*.restoring*"))


def test_a_file_that_is_not_a_dump_is_refused(tmp_path):
    with pytest.raises(RestoreRefused, match="schema_version"):
        restore('INSERT INTO "reviews" ("id") VALUES (1);\n', tmp_path / "x.db")
    with pytest.raises(RestoreRefused, match="partway"):
        parse_dump('INSERT INTO "reviews" ("id") VALUES (\'unterminated\n')


async def test_the_server_starts_against_a_restored_tracker_and_reads_it(mcp_server, tmp_path, monkeypatch):  # noqa: F811
    """No further step: the rebuilt file is a tracker the server opens as it opens any other."""
    from lifecycle_mcp.server import LifecycleMCPServer

    _, dump = await dumped(mcp_server)
    target = tmp_path / "restored.db"
    restore(dump, target)
    monkeypatch.setenv("LIFECYCLE_DB", str(target))
    server = LifecycleMCPServer()
    try:
        result = await call(server, "query_requirements", {})
        assert not result.isError, text_of(result)
        assert [r["id"] for r in result.structuredContent["requirements"]] == ["REQ-0001-FUNC-00"]
        assert tracker_rows(target)["reviews"] == 1
        details = await call(server, "get_details", {"entity_id": "REQ-0001-FUNC-00"})
        assert "split across lines" in text_of(details), "comments came back, line breaks and all"
    finally:
        server.db_manager.close()
