"""Schema migrations: one link store, atomic upgrades, and repair of damaged databases (roadmap R3)."""

import sqlite3
from pathlib import Path

import pytest

from lifecycle_mcp import migrations
from lifecycle_mcp.database_manager import DatabaseManager
from lifecycle_mcp.migrations import MIGRATIONS, MigrationError, apply_all_migrations
from lifecycle_mcp.server import LifecycleMCPServer

from .test_tool_results import REQUIREMENT, call, text_of

SCHEMA = Path(migrations.__file__).with_name("lifecycle-schema.sql")
LATEST = MIGRATIONS[-1][0]
LEGACY_TABLES = {"requirement_tasks", "requirement_architecture", "task_dependencies", "requirement_dependencies"}
LINK_VIEWS = (
    "requirement_progress",
    "task_hierarchy",
    "blocked_items",
    "requirement_hierarchy",
)


def database_at(path: Path, version: int) -> str:
    """A database created the way the server creates one, migrated only up to `version`."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.close()
    apply_all_migrations(str(path), target_version=version)
    return str(path)


def schema_version(db: str) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]


def names(db: str, kind: str) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def links(db: str) -> set[tuple]:
    with sqlite3.connect(db) as conn:
        return set(
            conn.execute("SELECT source_type, source_id, target_type, target_id, relationship_type FROM relationships")
        )


def schema_dump(db: str) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return sorted(conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))


SEED = """
    INSERT INTO requirements (id, requirement_number, type, title, priority, author, status) VALUES
        ('REQ-0001-FUNC-00', 1, 'FUNC', 'Parent requirement', 'P1', 'tests', 'Approved'),
        ('REQ-0002-FUNC-00', 2, 'FUNC', 'Child requirement', 'P1', 'tests', 'Approved');
    INSERT INTO tasks (id, task_number, subtask_number, title, priority, status) VALUES
        ('TASK-0001-00-00', 1, 0, 'Build', 'P1', 'In Progress'),
        ('TASK-0001-01-00', 1, 1, 'Build part', 'P1', 'Complete'),
        ('TASK-0002-00-00', 2, 0, 'Test', 'P1', 'Not Started');
    INSERT INTO architecture (id, type, title, status) VALUES ('ADR-0001', 'ADR', 'Decision', 'Accepted');
"""


# --- fresh databases -----------------------------------------------------------------------------


def test_fresh_database_has_one_link_store_and_an_intact_tasks_table(tmp_path):
    db = str(tmp_path / "fresh.db")
    DatabaseManager(db).close()

    assert schema_version(db) == LATEST
    tables = names(db, "table")
    assert "relationships" in tables
    assert not LEGACY_TABLES & tables
    with sqlite3.connect(db) as conn:
        assert "parent_task_id" not in {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        tasks_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'tasks'").fetchone()[0]
        for view in LINK_VIEWS:
            conn.execute(f"SELECT * FROM {view}").fetchall()
    assert "PRIMARY KEY" in tasks_sql and "CHECK (status IN" in tasks_sql and "DEFAULT 'Not Started'" in tasks_sql


def test_running_migrations_again_changes_nothing(tmp_path):
    db = str(tmp_path / "idempotent.db")
    DatabaseManager(db).close()
    before = schema_dump(db)
    assert apply_all_migrations(db) == LATEST
    assert schema_dump(db) == before


# --- existing databases ---------------------------------------------------------------------------


def test_legacy_links_are_copied_normalised_and_counted(tmp_path):
    db = database_at(tmp_path / "legacy.db", version=7)
    conn = sqlite3.connect(db)
    conn.executescript(
        SEED
        + """
        UPDATE tasks SET parent_task_id = 'TASK-0001-00-00' WHERE id = 'TASK-0001-01-00';
        INSERT INTO requirement_tasks (requirement_id, task_id) VALUES
            ('REQ-0001-FUNC-00', 'TASK-0001-00-00'),
            ('REQ-0001-FUNC-00', 'TASK-0001-01-00');
        INSERT INTO requirement_architecture (requirement_id, architecture_id, relationship_type)
            VALUES ('REQ-0001-FUNC-00', 'ADR-0001', 'addresses');
        INSERT INTO task_dependencies (task_id, depends_on_task_id, dependency_type)
            VALUES ('TASK-0002-00-00', 'TASK-0001-00-00', 'requires');
        INSERT INTO requirement_dependencies (requirement_id, depends_on_requirement_id, dependency_type)
            VALUES ('REQ-0002-FUNC-00', 'REQ-0001-FUNC-00', 'parent');
        -- create_relationship used to store requirement links in either direction
        INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type)
            VALUES ('rel-reversed', 'task', 'TASK-0002-00-00', 'requirement', 'REQ-0002-FUNC-00', 'implements');
        UPDATE requirements SET task_count = 99, tasks_completed = 99 WHERE id = 'REQ-0002-FUNC-00';
    """
    )
    conn.close()

    assert apply_all_migrations(db) == LATEST

    assert links(db) == {
        ("requirement", "REQ-0001-FUNC-00", "task", "TASK-0001-00-00", "implements"),
        ("requirement", "REQ-0001-FUNC-00", "task", "TASK-0001-01-00", "implements"),
        ("requirement", "REQ-0001-FUNC-00", "architecture", "ADR-0001", "addresses"),
        ("task", "TASK-0001-01-00", "task", "TASK-0001-00-00", "parent"),
        ("task", "TASK-0002-00-00", "task", "TASK-0001-00-00", "requires"),
        ("requirement", "REQ-0002-FUNC-00", "requirement", "REQ-0001-FUNC-00", "parent"),
        ("requirement", "REQ-0002-FUNC-00", "task", "TASK-0002-00-00", "implements"),
    }
    assert not LEGACY_TABLES & names(db, "table")
    with sqlite3.connect(db) as conn:
        counters = dict(
            (row[0], (row[1], row[2]))
            for row in conn.execute("SELECT id, task_count, tasks_completed FROM requirements")
        )
        assert counters == {"REQ-0001-FUNC-00": (2, 1), "REQ-0002-FUNC-00": (1, 0)}
        assert conn.execute("SELECT id, blocking_items FROM blocked_items").fetchall() == [
            ("TASK-0002-00-00", "TASK-0001-00-00")
        ]
        assert ("TASK-0001-01-00", "TASK-0001-00-00", 1) in conn.execute(
            "SELECT id, parent_task_id, level FROM task_hierarchy"
        ).fetchall()
        assert ("REQ-0002-FUNC-00", "REQ-0001-FUNC-00", 1) in conn.execute(
            "SELECT id, parent_requirement_id, hierarchy_level FROM requirement_hierarchy"
        ).fetchall()
        assert conn.execute(
            "SELECT architecture_artifacts FROM requirement_progress WHERE id = 'REQ-0001-FUNC-00'"
        ).fetchone() == (1,)


def test_database_damaged_by_the_partial_migration_7_gets_working_views_and_triggers(tmp_path):
    db = database_at(tmp_path / "damaged.db", version=6)
    conn = sqlite3.connect(db)
    conn.executescript(
        SEED
        + """
        INSERT INTO requirement_tasks (requirement_id, task_id) VALUES ('REQ-0001-FUNC-00', 'TASK-0002-00-00');
        INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type)
            VALUES ('rel-dep', 'task', 'TASK-0002-00-00', 'task', 'TASK-0001-00-00', 'depends');
        -- What the old migration 7 left behind: two legacy tables dropped, views still pointing at them.
        DROP TABLE task_dependencies;
        DROP TABLE requirement_dependencies;
    """
    )
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("SELECT * FROM blocked_items").fetchall()
    conn.close()

    assert apply_all_migrations(db) == LATEST

    with sqlite3.connect(db) as conn:
        for view in LINK_VIEWS:
            conn.execute(f"SELECT * FROM {view}").fetchall()
        assert [row[0] for row in conn.execute("SELECT id FROM blocked_items")] == ["TASK-0002-00-00"]
        # Triggers work again: completing the linked task updates the requirement's counter.
        conn.execute("UPDATE tasks SET status = 'Complete' WHERE id = 'TASK-0002-00-00'")
        assert conn.execute(
            "SELECT task_count, tasks_completed FROM requirements WHERE id = 'REQ-0001-FUNC-00'"
        ).fetchone() == (1, 1)


def test_failed_migration_rolls_back_and_stops_startup(tmp_path, monkeypatch):
    db = str(tmp_path / "atomic.db")
    DatabaseManager(db).close()

    def broken(conn):
        conn.execute("CREATE TABLE should_not_survive (x)")
        conn.execute("ALTER TABLE tasks DROP COLUMN no_such_column")

    monkeypatch.setattr(migrations, "MIGRATIONS", [*MIGRATIONS, (LATEST + 1, "broken on purpose", broken)])

    with pytest.raises(MigrationError, match=f"Migration {LATEST + 1}"):
        DatabaseManager(db)
    assert schema_version(db) == LATEST
    assert "should_not_survive" not in names(db, "table")


# --- edit tracking and decomposition clean-up (roadmap R6a / R6b) --------------------------------

EVENT_COLUMNS = "id, entity_type, entity_id, event_type, from_value, to_value, actor, occurred_at"


def test_edit_tracking_adds_revisions_and_event_fields_without_touching_existing_events(tmp_path):
    db = database_at(tmp_path / "events.db", version=8)
    with sqlite3.connect(db) as conn:
        conn.executescript(SEED)
        conn.execute(
            "INSERT INTO lifecycle_events (entity_type, entity_id, event_type, from_value, to_value, actor) "
            "VALUES ('requirement', 'REQ-0001-FUNC-00', 'status_change', 'Draft', 'Approved', 'tests')"
        )
        before = conn.execute(f"SELECT {EVENT_COLUMNS} FROM lifecycle_events ORDER BY id").fetchall()

    assert apply_all_migrations(db) == LATEST

    with sqlite3.connect(db) as conn:
        for table in ("requirements", "tasks", "architecture"):
            assert conn.execute(f"SELECT DISTINCT revision FROM {table}").fetchall() == [(0,)]
        assert {"field", "reason"} <= {row[1] for row in conn.execute("PRAGMA table_info(lifecycle_events)")}
        assert conn.execute(f"SELECT {EVENT_COLUMNS} FROM lifecycle_events ORDER BY id").fetchall() == before


def test_decomposition_objects_are_gone_but_hierarchy_and_cycle_check_remain(tmp_path):
    db = str(tmp_path / "decomposition.db")
    DatabaseManager(db).close()

    assert "decomposition_candidates" not in names(db, "view")
    assert not {"validate_decomposition_level", "set_decomposition_level"} & names(db, "trigger")
    assert "prevent_circular_dependencies" in names(db, "trigger")

    with sqlite3.connect(db) as conn:
        view_columns = {column[0] for column in conn.execute("SELECT * FROM requirement_hierarchy").description}
        assert not {"decomposition_level", "complexity_score", "scope_assessment"} & view_columns

        conn.executescript(
            SEED
            + """
            INSERT INTO requirements (id, requirement_number, type, title, priority, author, status) VALUES
                ('REQ-0003-FUNC-00', 3, 'FUNC', 'Level 2', 'P1', 'tests', 'Draft'),
                ('REQ-0004-FUNC-00', 4, 'FUNC', 'Level 3', 'P1', 'tests', 'Draft'),
                ('REQ-0005-FUNC-00', 5, 'FUNC', 'Level 4', 'P1', 'tests', 'Draft');
        """
        )
        chain = ["REQ-0001-FUNC-00", "REQ-0002-FUNC-00", "REQ-0003-FUNC-00", "REQ-0004-FUNC-00", "REQ-0005-FUNC-00"]
        # The old depth trigger refused a parent at level 3; a four-level chain is now allowed.
        for parent, child in zip(chain, chain[1:], strict=False):
            conn.execute(
                "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) "
                "VALUES (?, 'requirement', ?, 'requirement', ?, 'parent')",
                (f"rel-{child}-{parent}-parent", child, parent),
            )
        assert conn.execute(
            "SELECT hierarchy_level, root_requirement_id FROM requirement_hierarchy WHERE id = 'REQ-0005-FUNC-00'"
        ).fetchone() == (4, "REQ-0001-FUNC-00")

        with pytest.raises(sqlite3.DatabaseError, match="Circular dependency"):
            conn.execute(
                "INSERT INTO relationships (id, source_type, source_id, target_type, target_id, relationship_type) "
                "VALUES ('rel-cycle', 'requirement', 'REQ-0001-FUNC-00', 'requirement', 'REQ-0005-FUNC-00', 'parent')"
            )


def test_dead_columns_are_dropped_and_live_data_and_constraints_survive(tmp_path):
    db = database_at(tmp_path / "dead-columns.db", version=10)
    with sqlite3.connect(db) as conn:
        conn.executescript(SEED)
        conn.execute(
            "UPDATE requirements SET business_value = 'kept', gap_analysis = 'dropped' WHERE id = 'REQ-0001-FUNC-00'"
        )

    assert apply_all_migrations(db) == LATEST

    assert "idx_requirements_decomposition" not in names(db, "index")
    with sqlite3.connect(db) as conn:
        for table, dead in migrations.DEAD_COLUMNS.items():
            remaining = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert not set(dead) & remaining, table
        assert conn.execute("SELECT business_value FROM requirements WHERE id = 'REQ-0001-FUNC-00'").fetchone() == (
            "kept",
        )
        assert conn.execute("SELECT COUNT(*) FROM requirements").fetchone() == (2,)
        for view in LINK_VIEWS:
            conn.execute(f"SELECT * FROM {view}").fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE requirements SET priority = 'P9' WHERE id = 'REQ-0001-FUNC-00'")


# --- through the MCP layer: links survive a restart ------------------------------------------------


async def test_links_survive_a_restart_and_power_trace_blocked_items_and_diagrams(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFECYCLE_DB", str(tmp_path / "restart.db"))
    first = LifecycleMCPServer()
    first.requirement_handler._testing_mode = True
    req = "REQ-0001-FUNC-00"

    assert not (await call(first, "create_requirement", REQUIREMENT)).isError
    for status in ("Under Review", "Approved"):
        await call(first, "update_requirement_status", {"requirement_id": req, "new_status": status})
    decision = {"requirement_ids": [req], "title": "Use FTS5", "context": "Need search", "decision": "SQLite FTS5"}
    assert not (await call(first, "create_architecture_decision", decision)).isError
    base = {"requirement_ids": [req], "priority": "P1"}
    await call(first, "create_task", {**base, "title": "Build index"})  # TASK-0001-00-00
    await call(first, "create_task", {**base, "title": "Tokeniser", "parent_task_id": "TASK-0001-00-00"})
    await call(first, "create_task", {"requirement_ids": ["REQ-0001-FUNC-00"], "priority": "P2", "title": "Ranking"})
    dependency = {"source_id": "TASK-0002-00-00", "target_id": "TASK-0001-00-00", "relationship_type": "depends"}
    assert not (await call(first, "create_relationship", dependency)).isError
    first.db_manager.close()

    second = LifecycleMCPServer()  # a new session against the same database

    trace = await call(second, "trace_requirement", {"requirement_id": req})
    assert not trace.isError, text_of(trace)
    for linked in ("TASK-0001-00-00", "TASK-0001-01-00", "TASK-0002-00-00", "ADR-0001"):
        assert linked in text_of(trace)

    status = text_of(await call(second, "get_project_status", {"include_blocked": True}))
    assert "Blocked Items" in status and "TASK-0002-00-00" in status

    dependencies = await call(
        second, "create_architectural_diagrams", {"diagram_type": "dependencies", "output_path": str(tmp_path)}
    )
    assert "TASK_0001_00_00 --> TASK_0002_00_00" in text_of(dependencies)
    tasks = await call(second, "create_architectural_diagrams", {"diagram_type": "tasks", "output_path": str(tmp_path)})
    assert "TASK_0001_00_00 --> TASK_0001_01_00" in text_of(tasks)

    for task_id in ("TASK-0001-00-00", "TASK-0001-01-00", "TASK-0002-00-00"):
        await call(second, "update_task_status", {"task_id": task_id, "new_status": "Complete"})
    details = text_of(await call(second, "get_requirement_details", {"requirement_id": req}))
    assert "Linked Tasks (3)" in details
    for status_name in ("Architecture", "Ready", "Implemented", "Validated"):
        result = await call(second, "update_requirement_status", {"requirement_id": req, "new_status": status_name})
        assert not result.isError, text_of(result)
    second.db_manager.close()


async def test_reverse_direction_requirement_links_are_stored_one_way(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFECYCLE_DB", str(tmp_path / "direction.db"))
    server = LifecycleMCPServer()
    server.requirement_handler._testing_mode = True
    await call(server, "create_requirement", REQUIREMENT)
    for status in ("Under Review", "Approved"):
        await call(server, "update_requirement_status", {"requirement_id": "REQ-0001-FUNC-00", "new_status": status})
    other = {**REQUIREMENT, "title": "Other requirement"}
    await call(server, "create_requirement", other)
    await call(server, "create_task", {"requirement_ids": ["REQ-0001-FUNC-00"], "title": "Task", "priority": "P1"})

    reverse = {"source_id": "TASK-0001-00-00", "target_id": "REQ-0002-FUNC-00", "relationship_type": "implements"}
    assert not (await call(server, "create_relationship", reverse)).isError
    duplicate = {"source_id": "REQ-0002-FUNC-00", "target_id": "TASK-0001-00-00", "relationship_type": "implements"}
    assert (await call(server, "create_relationship", duplicate)).isError

    trace = text_of(await call(server, "trace_requirement", {"requirement_id": "REQ-0002-FUNC-00"}))
    assert "TASK-0001-00-00" in trace
    assert (await call(server, "delete_relationship", reverse)).isError is False
    assert "TASK-0001-00-00" not in text_of(
        await call(server, "trace_requirement", {"requirement_id": "REQ-0002-FUNC-00"})
    )
    server.db_manager.close()
