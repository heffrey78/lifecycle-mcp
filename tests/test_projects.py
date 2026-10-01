"""Projects: a named group of requirements and the purpose that group serves.

Exported documents had no owning concept: a list of requirements by type, with nothing saying what the group was for,
so whoever handed the export on wrote that summary by hand afterwards. A project holds the purpose as a stored field,
and export opens with it. Three owner decisions shape the rest (2026-09-30): a project is its own kind of record and
not a requirement at the top of a parent tree, a requirement can be in several projects (an epic and a layer at once),
and only requirements are members - tasks and decisions come along through their links.
"""

import os
import sqlite3

from lifecycle_mcp import dump
from lifecycle_mcp.database_manager import create_baseline
from lifecycle_mcp.migrations import apply_all_migrations

from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)

PURPOSE = "Let a reader find any note in under a second, without knowing where it was filed."
PROJECT = {
    "title": "Search",
    "purpose": PURPOSE,
    "success_criteria": ["Median query under 200 ms"],
    "out_of_scope": ["Searching attachments"],
}


async def ok(server, tool: str, arguments: dict):
    result = await call(server, tool, arguments)
    assert not result.isError, text_of(result)
    return result


async def requirement(server, title: str, **extra) -> str:
    result = await ok(server, "create_requirement", {**REQUIREMENT, "title": title, **extra})
    return result.structuredContent["id"]


async def approved_requirement(server, title: str) -> str:
    """A requirement far enough along to take tasks and decisions"""
    req_id = await requirement(server, title)
    for status in ("Under Review", "Approved"):
        await ok(server, "update_requirement_status", {"requirement_id": req_id, "new_status": status})
    return req_id


async def project(server, **extra) -> str:
    return (await ok(server, "create_project", {**PROJECT, **extra})).structuredContent["id"]


def rows(server, sql: str, params=()) -> list[tuple]:
    with sqlite3.connect(server.db_manager.db_path) as conn:
        return conn.execute(sql, params).fetchall()


def written(tmp_path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in tmp_path.iterdir()}


async def exported(server, tmp_path, **arguments) -> dict[str, str]:
    await ok(server, "export_project_documentation", {"output_directory": str(tmp_path), **arguments})
    return written(tmp_path)


# --- the record ----------------------------------------------------------------------------------


async def test_a_project_is_created_with_its_purpose_and_its_first_requirements(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    result = await ok(mcp_server, "create_project", {**PROJECT, "requirement_ids": [ids["requirement"]]})

    assert result.structuredContent["id"] == "PROJ-0001"
    report = text_of(await ok(mcp_server, "get_details", {"entity_id": "PROJ-0001"}))
    assert f"## Purpose\n{PURPOSE}\n" in report
    assert "### Success Criteria\n- Median query under 200 ms\n" in report
    assert "### Out of Scope\n- Searching attachments\n" in report
    assert "## Requirements (1)\n- REQ-0001-FUNC-00: Searchable notes [Approved] P1 - 0/1 tasks\n" in report
    assert "**Progress**: 1 requirement (1 Approved) | 0/1 tasks complete" in report
    assert "## Decisions (1)\n- ADR-0001: Use FTS5 [Proposed]\n" in report


async def test_a_project_without_a_purpose_is_refused(mcp_server):  # noqa: F811
    result = await call(mcp_server, "create_project", {"title": "Search", "purpose": "   "})

    assert result.isError
    assert "purpose" in text_of(result)
    assert rows(mcp_server, "SELECT COUNT(*) FROM projects") == [(0,)]


async def test_an_unknown_requirement_refuses_the_whole_project(mcp_server):  # noqa: F811
    req_id = await requirement(mcp_server, "Ranking")

    result = await call(mcp_server, "create_project", {**PROJECT, "requirement_ids": [req_id, "REQ-0099-FUNC-00"]})

    assert result.isError
    assert "No requirement REQ-0099-FUNC-00; nothing was created" in text_of(result)
    assert rows(mcp_server, "SELECT COUNT(*) FROM projects") == [(0,)]
    assert rows(mcp_server, "SELECT COUNT(*) FROM relationships") == [(0,)]


async def test_a_requirement_can_be_in_several_projects_and_says_so(mcp_server):  # noqa: F811
    req_id = await requirement(mcp_server, "Ranking")
    await project(mcp_server, title="Search epic", requirement_ids=[req_id])
    await project(mcp_server, title="Storage layer", requirement_ids=[req_id])

    report = text_of(await ok(mcp_server, "get_details", {"entity_id": req_id}))

    assert "## Projects (2)\n- PROJ-0001: Search epic [Active]\n- PROJ-0002: Storage layer [Active]\n" in report


async def test_a_requirement_can_be_created_inside_its_projects(mcp_server):  # noqa: F811
    project_id = await project(mcp_server)

    result = await ok(mcp_server, "create_requirement", {**REQUIREMENT, "project_ids": [project_id]})

    assert result.structuredContent["projects"] == [project_id]
    found = await ok(mcp_server, "query_requirements", {"project_id": project_id})
    assert [row["id"] for row in found.structuredContent["requirements"]] == [result.structuredContent["id"]]


async def test_an_unknown_project_refuses_the_requirement(mcp_server):  # noqa: F811
    result = await call(mcp_server, "create_requirement", {**REQUIREMENT, "project_ids": ["PROJ-0009"]})

    assert result.isError
    assert "No project PROJ-0009; nothing was created" in text_of(result)
    assert rows(mcp_server, "SELECT COUNT(*) FROM requirements") == [(0,)]


# --- editing and membership ----------------------------------------------------------------------


async def test_update_project_edits_and_changes_membership_in_one_revision(mcp_server):  # noqa: F811
    first, second = await requirement(mcp_server, "Ranking"), await requirement(mcp_server, "Indexing")
    project_id = await project(mcp_server, requirement_ids=[first])

    result = await ok(
        mcp_server,
        "update_project",
        {
            "project_id": project_id,
            "purpose": "Find any note in under a second.",
            "add_requirement_ids": [second],
            "remove_requirement_ids": [first],
            "reason": "Ranking moved to its own epic",
        },
    )

    assert result.structuredContent == {"id": project_id, "changed": ["purpose", "requirements"], "revision": 1}
    members = rows(mcp_server, "SELECT source_id FROM relationships WHERE target_id = ?", [project_id])
    assert members == [(second,)]
    history = text_of(await ok(mcp_server, "get_entity_history", {"entity_id": project_id}))
    assert "edited purpose" in history and "edited requirements" in history
    assert "reason: Ranking moved to its own epic" in history


async def test_a_refused_membership_change_writes_nothing(mcp_server):  # noqa: F811
    inside, outside = await requirement(mcp_server, "Ranking"), await requirement(mcp_server, "Indexing")
    project_id = await project(mcp_server, requirement_ids=[inside])

    stranger = await call(
        mcp_server,
        "update_project",
        {"project_id": project_id, "title": "Renamed", "remove_requirement_ids": [outside]},
    )
    missing = await call(
        mcp_server, "update_project", {"project_id": project_id, "add_requirement_ids": ["REQ-0099-FUNC-00"]}
    )

    assert stranger.isError and f"Not in {project_id}: {outside}" in text_of(stranger)
    assert missing.isError and "No requirement REQ-0099-FUNC-00" in text_of(missing)
    assert rows(mcp_server, "SELECT title, revision FROM projects") == [("Search", 0)]
    assert rows(mcp_server, "SELECT source_id FROM relationships WHERE target_id = ?", [project_id]) == [(inside,)]


async def test_a_project_is_closed_through_update_project(mcp_server):  # noqa: F811
    project_id = await project(mcp_server)

    await ok(mcp_server, "update_project", {"project_id": project_id, "status": "Closed"})

    assert rows(mcp_server, "SELECT status FROM projects") == [("Closed",)]


async def test_create_relationship_links_a_requirement_to_a_project_from_either_end(mcp_server):  # noqa: F811
    first, second = await requirement(mcp_server, "Ranking"), await requirement(mcp_server, "Indexing")
    project_id = await project(mcp_server)

    await ok(
        mcp_server, "create_relationship", {"source_id": first, "target_id": project_id, "relationship_type": "part_of"}
    )
    await ok(
        mcp_server,
        "create_relationship",
        {"source_id": project_id, "target_id": second, "relationship_type": "part_of"},
    )

    stored = rows(mcp_server, "SELECT source_type, source_id, target_type FROM relationships ORDER BY source_id")
    assert stored == [("requirement", first, "project"), ("requirement", second, "project")]

    await ok(mcp_server, "delete_relationship", {"source_id": project_id, "target_id": first})
    assert rows(mcp_server, "SELECT source_id FROM relationships") == [(second,)]


async def test_projects_take_short_ids_comments_and_history(mcp_server):  # noqa: F811
    await project(mcp_server)

    await ok(mcp_server, "add_comment", {"entity_id": "PROJ-1", "comment": "Agreed with the search team"})

    report = text_of(await ok(mcp_server, "get_details", {"entity_id": "proj-1"}))
    assert "# Project Details: PROJ-0001" in report
    assert "## Comments (1)" in report and "Agreed with the search team" in report
    history = text_of(await ok(mcp_server, "get_entity_history", {"entity_id": "PROJ-1"}))
    assert "created by MCP User" in history and "comment by MCP User" in history


async def test_a_project_holding_requirements_is_not_deleted(mcp_server):  # noqa: F811
    req_id = await requirement(mcp_server, "Ranking")
    project_id = await project(mcp_server, requirement_ids=[req_id])

    refused = await call(mcp_server, "delete_record", {"entity_id": project_id})

    assert refused.isError
    assert f"still holds 1 requirement(s) ({req_id})" in text_of(refused)
    assert "Closed" in text_of(refused)

    await ok(mcp_server, "update_project", {"project_id": project_id, "remove_requirement_ids": [req_id]})
    await ok(mcp_server, "delete_record", {"entity_id": project_id})
    assert rows(mcp_server, "SELECT COUNT(*) FROM projects") == [(0,)]
    assert rows(mcp_server, "SELECT COUNT(*) FROM requirements") == [(1,)]


async def test_deleting_a_requirement_takes_it_out_of_its_projects(mcp_server):  # noqa: F811
    req_id = await requirement(mcp_server, "Ranking")
    project_id = await project(mcp_server, requirement_ids=[req_id])

    await ok(mcp_server, "delete_record", {"entity_id": req_id})

    assert rows(mcp_server, "SELECT COUNT(*) FROM relationships WHERE target_id = ?", [project_id]) == [(0,)]


# --- reading by project --------------------------------------------------------------------------


async def test_tasks_are_found_through_the_requirements_of_a_project(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    other = await approved_requirement(mcp_server, "Indexing")
    await ok(mcp_server, "create_task", {"requirement_ids": [other], "title": "Outside", "priority": "P2"})
    project_id = await project(mcp_server, requirement_ids=[ids["requirement"]])

    found = await ok(mcp_server, "query_tasks", {"project_id": project_id})

    assert [task["id"] for task in found.structuredContent["tasks"]] == [ids["task"]]
    assert f"project: {project_id}" in text_of(found)


async def test_the_dashboard_lists_active_projects_with_their_progress(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await requirement(mcp_server, "Indexing")
    await project(mcp_server, requirement_ids=[ids["requirement"]])
    closed = await project(mcp_server, title="Old epic")
    await ok(mcp_server, "update_project", {"project_id": closed, "status": "Closed"})

    status = await ok(mcp_server, "get_project_status", {})

    assert (
        "## Projects (1 active)\n"
        "- PROJ-0001: Search - 1 requirement (1 Approved) | 0/1 tasks complete\n"
        "- 1 closed\n"
        "- 1 requirement in no project\n"
    ) in text_of(status)
    assert [entry["id"] for entry in status.structuredContent["projects"]] == ["PROJ-0001", "PROJ-0002"]


async def test_a_tracker_without_projects_has_no_projects_section(mcp_server):  # noqa: F811
    await populate(mcp_server)

    status = await ok(mcp_server, "get_project_status", {})

    assert "Projects" not in text_of(status).replace("# Project Status Dashboard", "")
    assert "projects" not in status.structuredContent


# --- export --------------------------------------------------------------------------------------


async def test_the_whole_export_opens_with_each_project_and_what_it_is_for(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    loose = await requirement(mcp_server, "Indexing")
    await project(mcp_server, requirement_ids=[ids["requirement"]])

    document = (await exported(mcp_server, tmp_path, project_name="notes"))["notes-requirements.md"]

    overview = (
        "## Projects\n\n"
        "### PROJ-0001: Search\n\n"
        "- **Status**: Active\n\n"
        f"**Purpose**: {PURPOSE}\n\n"
        "**Success Criteria**:\n- Median query under 200 ms\n\n"
        "**Out of Scope**:\n- Searching attachments\n\n"
        "**Requirements**:\n- REQ-0001-FUNC-00: Searchable notes [Approved]\n\n"
        f"### In No Project\n\n- {loose}: Indexing [Draft]\n\n---\n\n"
    )
    assert overview in document
    assert document.index(overview) < document.index("## FUNC Requirements")
    assert "- **Projects**: PROJ-0001: Search\n" in document
    assert document.count("- **Projects**:") == 1


async def test_an_export_without_projects_reads_as_it_always_did(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)

    document = (await exported(mcp_server, tmp_path, project_name="notes"))["notes-requirements.md"]

    assert "Project" not in document
    assert document.startswith("# notes - Requirements Documentation\n\nGenerated on: ")


async def test_one_project_exports_its_purpose_and_only_its_own_records(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    other = await approved_requirement(mcp_server, "Indexing")
    await ok(mcp_server, "create_task", {"requirement_ids": [other], "title": "Outside task", "priority": "P2"})
    await ok(
        mcp_server,
        "create_architecture_decision",
        {"requirement_ids": [other], "title": "Outside decision", "context": "c", "decision": "d"},
    )
    project_id = await project(mcp_server, requirement_ids=[ids["requirement"]])

    files = await exported(mcp_server, tmp_path, project_id=project_id)

    assert sorted(files) == ["PROJ-0001-architecture.md", "PROJ-0001-requirements.md", "PROJ-0001-tasks.md"]
    for kind in ("Requirements", "Tasks", "Architecture"):
        document = files[f"PROJ-0001-{kind.lower()}.md"]
        assert document.startswith(f"# Search - {kind} Documentation\n\nGenerated on: ")
        assert f"**Project**: PROJ-0001 [Active]\n\n**Purpose**: {PURPOSE}\n\n" in document
        assert "Outside" not in document and "Indexing" not in document
    assert "### REQ-0001-FUNC-00: Searchable notes" in files["PROJ-0001-requirements.md"]
    assert "## Projects" not in files["PROJ-0001-requirements.md"]
    assert "Build index" in files["PROJ-0001-tasks.md"]
    assert "Use FTS5" in files["PROJ-0001-architecture.md"]


async def test_an_empty_project_still_exports_its_purpose(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)
    project_id = await project(mcp_server)

    files = await exported(mcp_server, tmp_path, project_id=project_id, project_name="search")

    assert list(files) == ["search-requirements.md"]
    assert f"**Purpose**: {PURPOSE}" in files["search-requirements.md"]
    assert "No requirements in this project yet." in files["search-requirements.md"]


async def test_exporting_an_unknown_project_is_an_error(mcp_server, tmp_path):  # noqa: F811
    result = await call(
        mcp_server, "export_project_documentation", {"project_id": "PROJ-0007", "output_directory": str(tmp_path)}
    )

    assert result.isError
    assert "Project PROJ-0007 not found" in text_of(result)
    assert os.listdir(tmp_path) == []


# --- the migration and the dump ------------------------------------------------------------------


def test_migration_19_keeps_links_comments_and_the_triggers_that_count_tasks(tmp_path):
    path = tmp_path / "old.db"
    create_baseline(path)
    assert apply_all_migrations(str(path), 18) == 18
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, author) "
            "VALUES ('REQ-0001-FUNC-00', 1, 'FUNC', 'Ranking', 'P1', 'me')"
        )
        for number in (1, 2):
            conn.execute(
                "INSERT INTO tasks (id, task_number, title, priority) VALUES (?, ?, 'Build', 'P1')",
                [f"TASK-000{number}-00-00", number],
            )
        conn.execute(
            "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) "
            "VALUES ('rel-1', 'requirement', 'REQ-0001-FUNC-00', 'task', 'TASK-0001-00-00', 'implements')"
        )
        for comment in ("first", "second", "third"):
            conn.execute(
                "INSERT INTO reviews (entity_type, entity_id, reviewer, comment) "
                "VALUES ('requirement', 'REQ-0001-FUNC-00', 'me', ?)",
                [comment],
            )
        conn.execute("DELETE FROM reviews WHERE comment = 'third'")

    assert apply_all_migrations(str(path)) >= 19

    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id, relationship_type FROM relationships").fetchall() == [("rel-1", "implements")]
        assert conn.execute("SELECT id, comment FROM reviews").fetchall() == [(1, "first"), (2, "second")]
        # The deleted comment's id stays retired, and the counter trigger still fires on the rebuilt table.
        conn.execute(
            "INSERT INTO reviews (entity_type, entity_id, reviewer, comment) VALUES ('project', 'PROJ-0001', 'me', 'x')"
        )
        assert conn.execute("SELECT MAX(id) FROM reviews").fetchone() == (4,)
        conn.execute(
            "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) "
            "VALUES ('rel-2', 'requirement', 'REQ-0001-FUNC-00', 'task', 'TASK-0002-00-00', 'implements')"
        )
        assert conn.execute("SELECT task_count FROM requirements").fetchone() == (2,)
        conn.execute(
            "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) "
            "VALUES ('rel-3', 'requirement', 'REQ-0001-FUNC-00', 'project', 'PROJ-0001', 'part_of')"
        )


async def test_joining_a_project_does_not_restamp_the_requirement(mcp_server):  # noqa: F811
    req_id = await requirement(mcp_server, "Ranking")
    with sqlite3.connect(mcp_server.db_manager.db_path) as conn:
        conn.execute("UPDATE requirements SET updated_at = '2020-01-01 00:00:00'")
        conn.execute("DROP TRIGGER update_requirement_timestamp")
        conn.execute("UPDATE requirements SET updated_at = '2020-01-01 00:00:00'")

    await project(mcp_server, requirement_ids=[req_id])

    assert rows(mcp_server, "SELECT updated_at, revision FROM requirements") == [("2020-01-01 00:00:00", 0)]


async def test_projects_travel_in_the_dump_and_come_back(mcp_server, tmp_path):  # noqa: F811
    req_id = await requirement(mcp_server, "Ranking")
    await project(mcp_server, requirement_ids=[req_id])
    await ok(mcp_server, "add_comment", {"entity_id": "PROJ-0001", "comment": "Agreed"})

    text = dump.export_rows(mcp_server.db_manager.db_path)
    restored = tmp_path / "restored.db"
    dump.restore(text, restored)

    assert text.index('INSERT INTO "projects"') < text.index('INSERT INTO "requirements"')
    with sqlite3.connect(restored) as conn:
        assert conn.execute("SELECT id, purpose FROM projects").fetchall() == [("PROJ-0001", PURPOSE)]
        assert conn.execute("SELECT source_id FROM relationships WHERE target_id = 'PROJ-0001'").fetchall() == [
            (req_id,)
        ]
    assert dump.export_rows(restored) == text


# --- the viewer ----------------------------------------------------------------------------------


async def test_the_viewer_shows_a_project_and_its_links_from_both_ends(mcp_server):  # noqa: F811
    from .test_viewer_links import page_for, page_links

    req_id = await requirement(mcp_server, "Ranking")
    project_id = await project(mcp_server, requirement_ids=[req_id])

    page = page_for(mcp_server)

    assert 'id="records-project"' in page and "find any note in under a second" in page
    assert page_links(page, project_id) == {"part_of": {("←", req_id)}}
    assert page_links(page, req_id) == {"part_of": {("→", project_id)}}
    assert "not in this tracker" not in page


def test_the_viewer_reads_a_tracker_from_before_projects(tmp_path):
    """The viewer never migrates what it opens, so an older tracker has no projects table to read."""
    from lifecycle_mcp.viewer.snapshot import read_snapshot

    path = tmp_path / "old.db"
    create_baseline(path)
    apply_all_migrations(str(path), 18)

    assert read_snapshot(path).projects == []
