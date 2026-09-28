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
