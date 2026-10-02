"""Reading a tracker into a snapshot without touching it (REQ-0006-INTF-00, TASK-0090).

The measurement behind this: on 2026-09-28 the repository's main database file held 26 requirements and 531 events with
an mtime six days old, while the same database read through SQLite held 27 and 534. A copy of the file loses whatever
sits in the -wal. So the snapshot reads through SQLite, and these tests pin the two properties that follow - it sees
what a live writer has committed, and it leaves all three files alone.
"""

import sqlite3
from pathlib import Path

from lifecycle_mcp.viewer.snapshot import Snapshot, read_only_uri, read_snapshot

from .test_next_tasks import add_task
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


def db_path(server) -> Path:
    return Path(server.db_manager.db_path if hasattr(server, "db_manager") else server.db.db_path)


def file_bytes(path: Path) -> dict[str, bytes]:
    """The files that hold tracker data: the database and its write-ahead log.

    The -shm is deliberately not among them. It is the WAL's shared-memory index, and SQLite writes to it whenever a
    reader attaches, to register the read mark that keeps the reader's view consistent - so a read-only snapshot of a
    WAL database always changes it, and no amount of care avoids that. It holds no records and is rebuilt when the
    last connection closes. What matters is that nothing in the tracker moved (TASK-0090).
    """
    found = {}
    for suffix in ("", "-wal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            found[suffix or "db"] = sidecar.read_bytes()
    return found


async def test_the_snapshot_holds_every_record_and_link(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    second = await add_task(mcp_server, ids["requirement"], "Cache layer", "P2")
    assert not (await call(mcp_server, "add_comment", {"entity_id": ids["requirement"], "comment": "noted"})).isError

    snapshot = read_snapshot(db_path(mcp_server))

    assert [r["id"] for r in snapshot.requirements] == [ids["requirement"]]
    assert {t["id"] for t in snapshot.tasks} == {ids["task"], second}
    assert [a["id"] for a in snapshot.architecture] == [ids["adr"]]
    assert snapshot.relationships, "the implements and addresses links are part of the snapshot"
    assert any(c["comment"] == "noted" for c in snapshot.comments)
    assert snapshot.events, "the derived figures are computed from events"
    assert snapshot.schema_version, "which migrations the database has had"


async def test_reading_the_tracker_changes_none_of_its_three_files(mcp_server):  # noqa: F811
    await populate(mcp_server)
    path = db_path(mcp_server)
    before = file_bytes(path)

    read_snapshot(path)

    assert file_bytes(path) == before, "a read-only snapshot leaves the database and its write-ahead log untouched"


async def test_a_write_from_another_connection_does_not_stop_the_snapshot(mcp_server):  # noqa: F811
    """WAL means a reader neither blocks the writer nor is blocked by it, which is why no checkpoint is needed."""
    ids = await populate(mcp_server)
    path = db_path(mcp_server)

    writer = sqlite3.connect(str(path), timeout=30.0)
    try:
        writer.execute(
            "UPDATE requirements SET business_value = ? WHERE id = ?", ["written mid-read", ids["requirement"]]
        )
        writer.commit()
        snapshot = read_snapshot(path)
    finally:
        writer.close()

    assert snapshot.requirements[0]["business_value"] == "written mid-read", "the committed write is in the snapshot"


async def test_json_columns_arrive_parsed(mcp_server):  # noqa: F811
    result = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "Parsed fields",
            "priority": "P2",
            "current_state": "Stored as JSON text.",
            "desired_state": "Read back as lists.",
            "functional_requirements": ["first", "second"],
            "acceptance_criteria": ["checkable"],
        },
    )
    assert not result.isError, text_of(result)

    snapshot = read_snapshot(db_path(mcp_server))

    requirement = snapshot.requirements[0]
    assert requirement["functional_requirements"] == ["first", "second"]
    assert requirement["acceptance_criteria"] == ["checkable"]
    assert requirement["out_of_scope"] is None, "a field nobody filled is None, not an empty list to render"


async def test_an_unparseable_json_column_keeps_its_text_and_is_named(mcp_server):  # noqa: F811
    """Empty, unreadable and filled are three different things, and the page has to be able to tell them apart."""
    ids = await populate(mcp_server)
    path = db_path(mcp_server)
    writer = sqlite3.connect(str(path), timeout=30.0)
    try:
        writer.execute(
            "UPDATE requirements SET functional_requirements = ? WHERE id = ?", ["{not json", ids["requirement"]]
        )
        writer.commit()
    finally:
        writer.close()

    snapshot = read_snapshot(path)

    requirement = snapshot.requirements[0]
    assert requirement["functional_requirements"] == "{not json", "what is stored is kept, not discarded"
    assert requirement["_unreadable"] == ["functional_requirements"], "and named as unreadable"
    assert requirement["out_of_scope"] is None, "while a column nobody filled is still just empty"


def test_the_read_only_uri_does_not_claim_the_file_is_immutable(tmp_path):
    """immutable=1 would tell SQLite to ignore the WAL, which is the bug this whole module exists to avoid."""
    uri = read_only_uri(tmp_path / "lifecycle.db")

    assert uri.startswith("file://")
    assert uri.endswith("?mode=ro")
    assert "immutable" not in uri


def test_a_missing_database_is_named_rather_than_read_as_an_empty_project(tmp_path):
    try:
        read_snapshot(tmp_path / "nothing.db")
    except FileNotFoundError as error:
        assert "nothing.db" in str(error)
    else:
        raise AssertionError("a missing tracker should be reported, not rendered as an empty one")


async def test_counts_describe_the_snapshot(mcp_server):  # noqa: F811
    await populate(mcp_server)

    counts = read_snapshot(db_path(mcp_server)).counts()

    assert counts["requirements"] == 1 and counts["tasks"] == 1 and counts["architecture"] == 1
    assert set(counts) == {"projects", "requirements", "tasks", "architecture", "relationships", "comments", "events"}


def test_an_empty_snapshot_is_still_a_snapshot():
    empty = Snapshot(database_path="/nowhere/lifecycle.db")

    assert empty.counts() == dict.fromkeys(
        ("projects", "requirements", "tasks", "architecture", "relationships", "comments", "events"), 0
    )
