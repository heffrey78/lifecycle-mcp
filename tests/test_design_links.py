"""Design links: tasks implement ADRs, and a newer ADR supersedes an older one (roadmap R9, ADR-0003)."""

import sqlite3

import pytest

from lifecycle_mcp.migrations import apply_all_migrations

from .test_migrations import LATEST, SEED, database_at, links, names
from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


def stored_links(server) -> set[tuple]:
    return links(server.db_manager.db_path)


def decision(server, architecture_id: str) -> tuple:
    with sqlite3.connect(server.db_manager.db_path) as conn:
        return conn.execute("SELECT status, superseded_by FROM architecture WHERE id = ?", [architecture_id]).fetchone()


async def link(server, source_id: str, target_id: str, relationship_type: str):
    return await call(
        server,
        "create_relationship",
        {"source_id": source_id, "target_id": target_id, "relationship_type": relationship_type},
    )


async def new_decision(server, requirement_id: str) -> str:
    result = await call(
        server,
        "create_architecture_decision",
        {
            "requirement_ids": [requirement_id],
            "title": "Use trigrams",
            "context": "Substring search",
            "decision": "FTS5",
        },
    )
    assert not result.isError, text_of(result)
    return result.structuredContent["id"]


async def move_decision(server, architecture_id: str, new_status: str):
    return await call(
        server, "update_architecture_status", {"architecture_id": architecture_id, "new_status": new_status}
    )


# --- tasks implement architecture decisions (TASK-0047) ------------------------------------------------------


async def test_a_task_implements_an_adr_in_either_order(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    stored = ("task", ids["task"], "architecture", ids["adr"], "implements")

    assert not (await link(mcp_server, ids["task"], ids["adr"], "implements")).isError
    reversed_link = await link(mcp_server, ids["adr"], ids["task"], "implements")

    assert reversed_link.isError and "Relationship already exists" in text_of(reversed_link)
    assert stored in stored_links(mcp_server)
    refused = await call(mcp_server, "delete_record", {"entity_id": ids["adr"]})
    assert refused.isError and ids["task"] in text_of(refused)

    removed = await call(mcp_server, "delete_relationship", {"source_id": ids["adr"], "target_id": ids["task"]})
    assert not removed.isError and stored not in stored_links(mcp_server)


# --- a newer decision supersedes an older one (TASK-0047) ----------------------------------------------------


async def test_superseding_links_the_decisions_and_moves_the_older_one(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    assert not (await move_decision(mcp_server, ids["adr"], "Accepted")).isError
    newer = await new_decision(mcp_server, ids["requirement"])

    result = await link(mcp_server, newer, ids["adr"], "supersedes")

    assert not result.isError, text_of(result)
    assert f"{ids['adr']} is now Superseded" in text_of(result)
    assert decision(mcp_server, ids["adr"]) == ("Superseded", newer)
    assert ("architecture", newer, "architecture", ids["adr"], "supersedes") in stored_links(mcp_server)
    history = text_of(await call(mcp_server, "get_entity_history", {"entity_id": ids["adr"]}))
    assert "status Accepted → Superseded" in history


async def test_superseding_refuses_itself_twice_backwards_and_unknown_decisions(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    newer = await new_decision(mcp_server, ids["requirement"])
    third = await new_decision(mcp_server, ids["requirement"])

    itself = await link(mcp_server, ids["adr"], ids["adr"], "supersedes")
    assert itself.isError and f"{ids['adr']} can't supersede itself" in text_of(itself)

    assert not (await link(mcp_server, newer, ids["adr"], "supersedes")).isError
    again = await link(mcp_server, third, ids["adr"], "supersedes")
    assert again.isError and f"{ids['adr']} is already superseded by {newer}" in text_of(again)

    backwards = await link(mcp_server, ids["adr"], third, "supersedes")
    assert backwards.isError and f"{ids['adr']} is itself Superseded" in text_of(backwards)

    unknown = await link(mcp_server, "ADR-0099", newer, "supersedes")
    assert unknown.isError and "Architecture decision ADR-0099 not found" in text_of(unknown)

    not_a_decision = await link(mcp_server, ids["task"], ids["adr"], "supersedes")
    assert not_a_decision.isError and "Invalid relationship" in text_of(not_a_decision)
    assert decision(mcp_server, third) == ("Proposed", None)


async def test_superseded_status_follows_the_supersedes_link(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    bare = await move_decision(mcp_server, ids["adr"], "Superseded")
    assert bare.isError and "relationship_type supersedes" in text_of(bare)
    assert decision(mcp_server, ids["adr"]) == ("Proposed", None)

    newer = await new_decision(mcp_server, ids["requirement"])
    assert not (await link(mcp_server, newer, ids["adr"], "supersedes")).isError
    leaving = await move_decision(mcp_server, ids["adr"], "Accepted")
    assert leaving.isError and f"{ids['adr']} is superseded by {newer}" in text_of(leaving)

    unlinked = await call(
        mcp_server,
        "delete_relationship",
        {"source_id": newer, "target_id": ids["adr"], "relationship_type": "supersedes"},
    )
    assert not unlinked.isError
    assert decision(mcp_server, ids["adr"]) == ("Superseded", None)
    assert not (await move_decision(mcp_server, ids["adr"], "Accepted")).isError


# --- migration 14 (TASK-0047) --------------------------------------------------------------------------------


def schema_objects(db: str, kind: str) -> set[str]:
    return {name for name in names(db, kind) if not name.startswith("sqlite_")}


def test_migration_14_allows_supersedes_and_keeps_every_link_object(tmp_path):
    db = database_at(tmp_path / "supersedes.db", version=13)
    before = {kind: schema_objects(db, kind) for kind in ("view", "trigger", "index")}
    with sqlite3.connect(db) as conn:
        conn.executescript(SEED)
        conn.executescript(
            """
            INSERT INTO architecture (id, type, title, status) VALUES ('ADR-0002', 'ADR', 'Replacement', 'Accepted');
            UPDATE architecture SET status = 'Superseded', superseded_by = 'ADR-0002' WHERE id = 'ADR-0001';
            INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type)
            VALUES ('rel-TASK-0002-00-00-TASK-0001-00-00-depends', 'task', 'TASK-0002-00-00', 'task', 'TASK-0001-00-00',
                    'depends');
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) "
                "VALUES ('x', 'architecture', 'ADR-0002', 'architecture', 'ADR-0001', 'supersedes')"
            )

    assert apply_all_migrations(db) == LATEST

    assert schema_objects(db, "view") == before["view"]
    assert schema_objects(db, "index") == before["index"]
    assert schema_objects(db, "trigger") == before["trigger"] | {"set_superseded_by", "clear_superseded_by"}
    assert ("task", "TASK-0002-00-00", "task", "TASK-0001-00-00", "depends") in links(db)
    assert ("architecture", "ADR-0002", "architecture", "ADR-0001", "supersedes") in links(db)
    with sqlite3.connect(db) as conn:
        # The recreated triggers and views still work against the rebuilt table.
        conn.execute(
            "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) "
            "VALUES ('rel-REQ-0001-FUNC-00-TASK-0001-00-00-implements', 'requirement', 'REQ-0001-FUNC-00', 'task', "
            "'TASK-0001-00-00', 'implements')"
        )
        assert conn.execute("SELECT task_count FROM requirements WHERE id = 'REQ-0001-FUNC-00'").fetchone() == (1,)
        assert conn.execute("SELECT id FROM blocked_items").fetchall() == [("TASK-0002-00-00",)]
        conn.execute("DELETE FROM relationships WHERE relationship_type = 'supersedes'")
        assert conn.execute("SELECT superseded_by FROM architecture WHERE id = 'ADR-0001'").fetchone() == (None,)
